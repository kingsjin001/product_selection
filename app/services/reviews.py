"""报告草稿人工复核：决定、剩余预算和任务重新投递在事务内保存。"""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select

from app.analysis_contracts import AnalysisRequest
from app.db.analysis_models import AnalysisRun
from app.db.interaction_models import ReportReview
from app.db.task_models import Task, TaskDispatch
from app.services.analysis_store import digest
from app.services.tasks import TaskConflict, TaskService, emit, utc


def review_reasons(request, report):
    """确定性复核触发器，避免把模型自信度当审核标准。"""
    if request.review_policy == "off":
        return []
    reasons = []
    if request.review_policy == "always":
        reasons.append("用户要求发布前复核")
    if report["economics"]["status"] != "ok":
        reasons.append("成本资料不完整")
    if report["research"]["missing_data"]:
        reasons.append("研究仍有待补充资料")
    if any(word in str(report["research"]) for word in ("冲突", "矛盾", "不一致")):
        reasons.append("研究包含相互冲突的信息")
    return reasons


def prepare_review(store, run_id, report, reasons):
    """节点重放只复用相同草稿；不覆盖已经作出的决定。"""
    draft_hash = digest(report)
    with store.factory.begin() as session:
        store.check_owner(session)
        row = session.get(ReportReview, run_id)
        if row is None:
            session.add(ReportReview(run_id=run_id, draft_hash=draft_hash, content=report,
                                    reasons=reasons, status="pending"))
        elif row.draft_hash != draft_hash:
            raise TaskConflict("复核草稿发生变化，请创建新运行")
    return {"run_id": run_id, "draft_hash": draft_hash, "reasons": reasons}


def mark_waiting(store, run_id, remaining_seconds=None):
    """仅在图已落盘中断之后释放租约，崩溃窗口可由原检查点重放收敛。"""
    with store.factory.begin() as session:
        task = store.check_owner(session)
        row = session.get(ReportReview, run_id)
        if row is None or row.status != "pending":
            raise TaskConflict("没有待处理草稿")
        row.waiting_at = datetime.now(UTC)
        if remaining_seconds is not None:
            row.remaining_seconds = max(0, remaining_seconds)
        if task:
            row.remaining_seconds = max(0, (utc(task.deadline_at) - row.waiting_at).total_seconds())
            task.status, task.stage = "waiting_for_review", "review"
            task.lease_until, task.deadline_at = None, None
            emit(session, task, "waiting_for_review", "草稿已保存，等待人工复核",
                 {"draft_hash": row.draft_hash, "reasons": row.reasons})
        session.get(AnalysisRun, run_id).status = "waiting_for_review"


def get_review(factory, run_id):
    """返回可审查草稿，不将其混入已发布报告库。"""
    with factory() as session:
        row = session.get(ReportReview, run_id)
        if row is None:
            raise ValueError("复核草稿不存在")
        return {"run_id": run_id, "draft_hash": row.draft_hash, "draft": row.content,
                "reasons": row.reasons, "status": row.status, "decision": row.decision,
                "remaining_seconds": row.remaining_seconds}


def decide_review(factory, settings, run_id, draft_hash, action, feedback=""):
    """校验摘要和当前状态；相同决定幂等，修改要求创建独立任务版本。"""
    if action not in {"approve", "reject", "request_changes"}:
        raise ValueError("不支持的复核决定")
    if action == "request_changes" and not feedback.strip():
        raise ValueError("请填写修改意见")
    service = TaskService(factory, settings)
    decision = {"action": action, "feedback": feedback}
    with factory.begin() as session:
        task = session.get(Task, run_id)
        if task:
            task = service.locked(session, run_id)
        row = session.scalar(select(ReportReview).where(
            ReportReview.run_id == run_id).with_for_update())
        if row is None or row.draft_hash != draft_hash:
            raise TaskConflict("草稿版本已变化或不存在，请刷新")
        run = session.get(AnalysisRun, run_id)
        if row.status != "pending":
            if row.decision != decision:
                raise TaskConflict("该草稿已经作出其他决定")
        else:
            if run.status != "waiting_for_review" or (task and task.status != "waiting_for_review"):
                raise TaskConflict("任务已取消或尚未进入等待复核状态")
            row.decision, row.status = decision, action
            if action == "approve":
                run.status = "pending"
                if task:
                    task.status, task.stage = "queued", "review_approved"
                    session.add(TaskDispatch(id=str(uuid4()), task_id=run_id))
                    emit(session, task, "review_approved", "草稿已批准，继续发布")
            else:
                run.status = "cancelled"
                if task:
                    task.status, task.stage = "cancelled", "review_rejected"
                    emit(session, task, "cancelled", "草稿未发布", decision)
        original, snapshot = run.request, run.snapshot
    result = {"run_id": run_id, "status": action}
    if action == "request_changes":
        # 稳定键使跨事务崩溃后的重复提交仍只创建一个后继任务。
        request = AnalysisRequest.model_validate({**original, "review_policy": "always",
            "question": (original["question"][:450] + "\n人工修改意见：" + feedback[:500])})
        result["revision_task_id"] = service.create(
            request, f"review-revision:{run_id}", snapshot_override=snapshot, parent_id=run_id)
    return result
