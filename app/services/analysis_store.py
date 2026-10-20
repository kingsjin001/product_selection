"""冻结分析输入，并持久化运行状态、报告和模型/工具调用预算。"""

import hashlib
import json
import logging
from contextlib import contextmanager
from datetime import UTC, datetime
from time import monotonic
from uuid import uuid4

from sqlalchemy import select

from app.analysis_contracts import AnalysisRequest
from app.core.config import Settings
from app.db.analysis_models import AnalysisCall, AnalysisReport, AnalysisRun
from app.db.index_models import EvidenceState
from app.db.models import Evidence, Product

logger = logging.getLogger(__name__)


def digest(value: dict) -> str:
    """对规范 JSON 求摘要，用于输入快照与报告完整性比较。"""
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def freeze_snapshot(session, request: AnalysisRequest) -> dict:
    """冻结商品、全部关联评论及同市场规则；后续工具仅读取这个快照。"""
    product = session.get(Product, request.product_id)
    if product is None:
        raise ValueError("商品不存在，请先导入商品数据")
    evidence = session.scalars(
        select(Evidence).outerjoin(EvidenceState, Evidence.id == EvidenceState.evidence_id).where(
            Evidence.market == product.market,
            (Evidence.product_id == product.id) | (Evidence.evidence_kind == "rule"),
            (EvidenceState.active.is_(True)) | (EvidenceState.evidence_id.is_(None)),
        ).order_by(Evidence.id)
    ).all()
    snapshot = {
        "product": {
            "id": product.id, "name": product.name, "market": product.market,
            "category": product.category, "specifications": product.specifications,
            "source_url": product.source_url,
        },
        "evidence": [
            {
                "id": item.id, "kind": item.evidence_kind, "product_id": item.product_id,
                "market": item.market, "category": item.category, "text": item.text,
                "version": item.content_version, "content_hash": item.content_hash,
                "source_url": item.source_url, "payload": item.payload,
                "observed_at": item.observed_at.isoformat() if item.observed_at else None,
            }
            for item in evidence
        ],
    }
    return {**snapshot, "hash": digest(snapshot)}


def analysis_versions(settings):
    """同步入口和后台入口共享版本及预算字段。"""
    return {
        "prompt": "research-v4", "schema": "report-v2",
        "model": settings.chat_model, "embedding": settings.embedding_model,
        "embedding_dim": settings.embedding_dim,
        "embedding_provider": settings.embedding_provider,
        "limits": {"model": settings.max_model_calls, "tool": settings.max_tool_calls,
                   "seconds": settings.agent_timeout_seconds},
    }


class AnalysisStore:
    """每次操作使用独立事务，适配 API、CLI 及并发工具调用。"""

    def __init__(self, factory, settings: Settings):
        """注入会话工厂，允许测试使用隔离数据库。"""
        self.factory = factory
        self.settings = settings
        self.guard = None
        self.on_complete = None
        self.on_stage = None

    def check_owner(self, session):
        """后台执行注入 fencing 检查；同步 CLI 保持原有单运行锁。"""
        if self.guard:
            return self.guard(session)

    def stage(self, name):
        """可选的持久阶段事件回调。"""
        if self.on_stage:
            self.on_stage(name)

    def create(self, request: AnalysisRequest) -> str:
        """在一笔事务内冻结输入并创建运行标识。"""
        with self.factory.begin() as session:
            run_id = str(uuid4())
            snapshot = freeze_snapshot(session, request)
            session.add(AnalysisRun(
                id=run_id, status="pending", request=request.model_dump(mode="json"),
                snapshot=snapshot,
                versions=analysis_versions(self.settings),
            ))
        return run_id

    def get(self, run_id: str) -> dict:
        """返回运行副本，不向调用者暴露 ORM 活动会话。"""
        with self.factory() as session:
            run = session.get(AnalysisRun, run_id)
            if run is None:
                raise ValueError("分析运行不存在")
            return {
                "id": run.id, "status": run.status, "request": run.request,
                "snapshot": run.snapshot, "versions": run.versions, "error": run.error,
                "usage": {
                    "model_calls": run.model_calls, "tool_calls": run.tool_calls,
                    "input_tokens": run.input_tokens, "output_tokens": run.output_tokens,
                },
            }

    def status(self, run_id: str, status: str, error: str | None = None) -> None:
        """更新状态；仅保存异常类别，避免将供应商响应中的敏感信息写入报告。"""
        with self.factory.begin() as session:
            self.check_owner(session)
            run = session.get(AnalysisRun, run_id)
            run.status = status
            run.error = error

    def report(self, run_id: str) -> dict | None:
        """读取同一运行唯一的已完成报告，供幂等重放。"""
        with self.factory() as session:
            row = session.get(AnalysisReport, run_id)
            return row.content if row else None

    def save_report(self, run_id: str, content: dict, markdown: str) -> None:
        """报告与运行终态在同一事务提交，重放时不覆盖已有报告。"""
        with self.factory.begin() as session:
            self.check_owner(session)
            run = session.scalar(
                select(AnalysisRun).where(AnalysisRun.id == run_id).with_for_update()
            )
            if session.get(AnalysisReport, run_id) is None:
                # 和更新/删除锁住相同证据行，避免校验与报告提交之间的竞态。
                frozen = {row["id"]: row for row in content["evidence"]}
                cited = {eid for claim in content["research"]["claims"]
                         for eid in claim["evidence_ids"]}
                for eid in sorted(cited):
                    evidence = session.scalar(
                        select(Evidence).where(Evidence.id == eid).with_for_update()
                    )
                    state = session.get(EvidenceState, eid)
                    if (evidence is None or (state and not state.active)
                            or evidence.content_hash != frozen[eid]["content_hash"]):
                        raise ValueError("证据已经更新或删除，请创建新的分析")
                session.add(AnalysisReport(
                    run_id=run_id, content=content, content_hash=digest(content), markdown=markdown,
                ))
            run.status = "completed"
            run.error = None
            if self.on_complete:
                self.on_complete(session)


class BudgetExceeded(RuntimeError):
    """调用次数或运行时间达到上限时中断研究。"""


class RunBudget:
    """数据库原子预留调用次数；进程重启不会重置已消费的额度。"""

    def __init__(self, store: AnalysisStore, run_id: str):
        """读取该运行创建时冻结的限制，开始本次执行的墙钟计时。"""
        self.store = store
        self.run_id = run_id
        self.limits = store.get(run_id)["versions"]["limits"]
        self.deadline = monotonic() + self.limits["seconds"]
        if store.guard:
            with store.factory.begin() as session:
                task = store.check_owner(session)
                deadline = task.deadline_at
                if deadline.tzinfo is None:
                    deadline = deadline.replace(tzinfo=UTC)
                self.deadline = monotonic() + (deadline - datetime.now(UTC)).total_seconds()

    def check(self) -> None:
        """在每次调用和节点边界检查执行时限。"""
        if monotonic() >= self.deadline:
            raise BudgetExceeded("本次执行时间预算已耗尽")
        if self.store.guard:
            with self.store.factory.begin() as session:
                self.store.check_owner(session)

    @contextmanager
    def call(self, kind: str, name: str):
        """先预留额度再调用，包含失败调用；工具多线程时通过行锁共享额度。"""
        self.check()
        call_id = str(uuid4())
        field = "model_calls" if kind == "model" else "tool_calls"
        with self.store.factory.begin() as session:
            self.store.check_owner(session)
            run = session.scalar(
                select(AnalysisRun).where(AnalysisRun.id == self.run_id).with_for_update()
            )
            used = getattr(run, field)
            if used >= self.limits[kind]:
                raise BudgetExceeded(f"{kind} 调用预算已耗尽")
            setattr(run, field, used + 1)
            session.add(AnalysisCall(
                id=call_id, run_id=self.run_id, kind=kind, name=name, status="started",
            ))
        started = monotonic()
        logger.info("调用开始 | run=%s kind=%s name=%s", self.run_id, kind, name)
        status, details = "ok", {}
        try:
            yield details
            self.check()
        except Exception as error:
            status = "failed"
            details["error_type"] = type(error).__name__
            raise
        finally:
            with self.store.factory.begin() as session:
                row = session.get(AnalysisCall, call_id)
                row.status = status
                row.latency_ms = int((monotonic() - started) * 1000)
                row.details = details
                if kind == "model":
                    run = session.scalar(
                        select(AnalysisRun).where(AnalysisRun.id == self.run_id).with_for_update()
                    )
                    run.input_tokens += int(details.get("input_tokens", 0))
                    run.output_tokens += int(details.get("output_tokens", 0))
            logger.info("调用结束 | run=%s name=%s status=%s elapsed=%.2fs",
                        self.run_id, name, status, monotonic() - started)
            logger.debug("调用详情 | run=%s name=%s details=%s", self.run_id, name, details)
