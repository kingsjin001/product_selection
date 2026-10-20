"""事务任务状态机、租约与完成事件；不依赖 Celery 内存状态判定结果。"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db.analysis_models import AnalysisRun
from app.db.task_models import Task, TaskDispatch, TaskEvent
from app.services.analysis_store import digest, freeze_snapshot

TERMINAL = {"completed", "failed", "cancelled"}


class TaskConflict(ValueError):
    """幂等键复用或非法状态迁移。"""


class OwnershipLost(RuntimeError):
    """任务已取消、租约过期或被新 Worker 接管。"""


def utc(value):
    """测试 SQLite 不保留时区，统一按 UTC 解释。"""
    return value.replace(tzinfo=UTC) if value and value.tzinfo is None else value


def emit(session, task, kind, message, payload=None):
    """调用者必须持有任务行锁，确保序号单调且没有重复。"""
    task.event_seq += 1
    session.add(TaskEvent(
        id=str(uuid4()), task_id=task.id, seq=task.event_seq, stage=task.stage,
        type=kind, message=message, payload=payload or {},
    ))


class TaskService:
    """状态变更使用短事务，模型调用不持有业务行锁。"""

    def __init__(self, factory, settings, lease_seconds=30):
        self.factory, self.settings, self.lease_seconds = factory, settings, lease_seconds

    def locked(self, session, task_id):
        """统一锁顺序：任务行在运行行之前。"""
        task = session.scalar(select(Task).where(Task.id == task_id).with_for_update())
        if task is None:
            raise ValueError("任务不存在")
        return task

    def create(self, request, key, *, snapshot_override=None, parent_id=None):
        """分析快照、任务、首次事件和投递记录在同一事务创建。"""
        payload = request.model_dump(mode="json")
        fingerprint = digest({"request": payload, "parent_id": parent_id} if parent_id else payload)
        try:
            with self.factory.begin() as session:
                existing = session.scalar(select(Task).where(Task.idempotency_key == key))
                if existing:
                    if existing.request_hash != fingerprint:
                        raise TaskConflict("相同幂等键对应不同请求")
                    return existing.id
                identity = str(uuid4())
                # 与同步入口使用同一版本字段定义。
                from app.services.analysis_store import analysis_versions
                versions = analysis_versions(self.settings)
                if parent_id:
                    versions["parent_run_id"] = parent_id
                session.add(AnalysisRun(
                    id=identity, status="pending", request=request.model_dump(mode="json"),
                    snapshot=(snapshot_override if snapshot_override is not None
                              else freeze_snapshot(session, request)),
                    versions=versions,
                ))
                task = Task(id=identity, idempotency_key=key, request_hash=fingerprint,
                            status="queued", stage="queued", epoch=0, attempts=0, event_seq=0)
                session.add(task)
                session.add(TaskDispatch(id=str(uuid4()), task_id=identity))
                emit(session, task, "queued", "任务已入队")
                return identity
        except IntegrityError:
            # 同时提交相同幂等键的请求等待唯一约束后回读。
            with self.factory() as session:
                existing = session.scalar(select(Task).where(Task.idempotency_key == key))
                if existing is None:
                    raise
                if existing.request_hash != fingerprint:
                    raise TaskConflict("相同幂等键对应不同请求") from None
                return existing.id

    def claim(self, task_id):
        """只有排队任务可以领取；重复消息和仍在运行的任务不重复执行。"""
        with self.factory.begin() as session:
            task = self.locked(session, task_id)
            if task.status != "queued":
                return None
            now = datetime.now(UTC)
            if task.attempts >= 5:
                task.status = "failed"
                emit(session, task, "failed", "自动执行次数已达到上限")
                return None
            task.epoch += 1
            task.attempts += 1
            task.status, task.stage = "running", "research"
            task.lease_until = now + timedelta(seconds=self.lease_seconds)
            if task.deadline_at is None:
                task.deadline_at = now + timedelta(seconds=self.settings.agent_timeout_seconds)
            emit(session, task, "started", "Worker 开始执行", {"attempt": task.attempts})
            return task.epoch

    def guard(self, session, task_id, epoch):
        """写入前验证 fencing epoch、取消状态与租约。"""
        task = self.locked(session, task_id)
        if (task.epoch != epoch or task.status != "running"
                or utc(task.lease_until) <= datetime.now(UTC)):
            raise OwnershipLost("任务已取消或执行权已失效")
        return task

    def heartbeat(self, task_id, epoch):
        """模型请求期间由独立线程续租，避免长请求被误判为进程死亡。"""
        with self.factory.begin() as session:
            task = self.guard(session, task_id, epoch)
            task.lease_until = datetime.now(UTC) + timedelta(seconds=self.lease_seconds)

    def stage(self, task_id, epoch, stage):
        """在确定性阶段边界记录进度；不伪造模型内部百分比。"""
        with self.factory.begin() as session:
            task = self.guard(session, task_id, epoch)
            task.stage = stage
            emit(session, task, "stage", f"进入阶段：{stage}")

    def complete(self, session, task_id, epoch):
        """由报告保存事务调用，保证报告与完成事件一同提交。"""
        task = self.guard(session, task_id, epoch)
        task.status, task.stage, task.lease_until = "completed", "completed", None
        task.error = None
        emit(session, task, "completed", "报告已保存", {"report_id": task_id})

    def fail(self, task_id, epoch, error):
        """失败和协作取消只允许当前 epoch 确认，旧进程不能修改终态。"""
        with self.factory.begin() as session:
            task = self.locked(session, task_id)
            if task.epoch != epoch or task.status in TERMINAL:
                return
            task.status = "cancelled" if task.status == "cancelling" else "failed"
            task.error, task.lease_until = type(error).__name__, None
            run = session.get(AnalysisRun, task_id)
            run.status, run.error = task.status, task.error
            emit(session, task, task.status, "执行已停止", {"error": task.error})

    def cancel(self, task_id):
        """运行中先标记 cancelling；排队时直接取消，不删除历史事件。"""
        with self.factory.begin() as session:
            task = self.locked(session, task_id)
            if task.status in TERMINAL or task.status == "cancelling":
                return
            task.status = "cancelled" if task.status == "queued" else "cancelling"
            session.get(AnalysisRun, task_id).status = task.status
            emit(session, task, task.status, "已请求取消")

    def resume(self, task_id):
        """失败可恢复同一快照与剩余额度；取消后需显式创建新的任务。"""
        with self.factory.begin() as session:
            task = self.locked(session, task_id)
            if task.status != "failed":
                raise TaskConflict("仅失败任务可恢复；取消或修改输入后请新建任务")
            if task.attempts >= 5 or (
                task.deadline_at and utc(task.deadline_at) <= datetime.now(UTC)
            ):
                raise TaskConflict("原运行的次数或时间预算已耗尽，请新建任务")
            task.status, task.stage, task.error = "queued", "queued", None
            session.get(AnalysisRun, task_id).status = "pending"
            session.add(TaskDispatch(id=str(uuid4()), task_id=task_id))
            emit(session, task, "resumed", "已请求从检查点恢复")

    def recover(self):
        """扫描过期租约，先递增 epoch 使旧 Worker 失权，再登记重新投递。"""
        now, count = datetime.now(UTC), 0
        with self.factory.begin() as session:
            tasks = session.scalars(select(Task).where(
                Task.status.in_(["running", "cancelling"]), Task.lease_until <= now,
            ).with_for_update(skip_locked=True)).all()
            for task in tasks:
                task.epoch += 1
                task.lease_until = None
                if task.status == "cancelling":
                    task.status = "cancelled"
                elif task.attempts >= 5 or utc(task.deadline_at) <= now:
                    task.status = "failed"
                else:
                    task.status, task.stage = "queued", "queued"
                    session.add(TaskDispatch(id=str(uuid4()), task_id=task.id))
                session.get(AnalysisRun, task.id).status = task.status
                emit(session, task, "recovered", f"租约过期，状态：{task.status}")
                count += 1
        return count

    def get(self, task_id):
        """提供刷新页面需要的状态快照，不依赖消息订阅是否在线。"""
        with self.factory() as session:
            task = session.get(Task, task_id)
            if task is None:
                raise ValueError("任务不存在")
            return {key: getattr(task, key) for key in (
                "id", "status", "stage", "epoch", "attempts", "event_seq", "error",
            )}

    def events(self, task_id, after=0):
        """读取序号之后的事件，供断线补发和测试复用。"""
        with self.factory() as session:
            rows = session.scalars(select(TaskEvent).where(
                TaskEvent.task_id == task_id, TaskEvent.seq > after,
            ).order_by(TaskEvent.seq).limit(200)).all()
            return [{"task_id": row.task_id, "run_id": row.task_id, "event_seq": row.seq,
                     "stage": row.stage, "type": row.type, "message": row.message,
                     "payload": row.payload, "timestamp": row.created_at.isoformat()}
                    for row in rows]
