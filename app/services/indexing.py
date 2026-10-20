"""证据更新/软删除与事务 outbox 同步，支持重试、重复事件和跨模型清理。"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import select

from app.core.embeddings import EmbeddingService
from app.db.index_models import EvidenceState, IndexEvent, VectorManifest
from app.db.models import Evidence
from app.repositories.vectors import EvidenceVectors
from app.services.analysis_store import digest


def enqueue_all(factory) -> int:
    """重建时为现存证据登记事件；重复执行幂等写回相同版本主键。"""
    with factory.begin() as session:
        rows = session.scalars(select(Evidence)).all()
        for row in rows:
            if session.get(EvidenceState, row.id) is None:
                session.add(EvidenceState(evidence_id=row.id, active=True, generation=1))
            session.add(IndexEvent(id=str(uuid4()), evidence_id=row.id))
        return len(rows)


def change_evidence(factory, evidence_id: str, *, content: str | None = None, delete=False):
    """变更或软删除与同步事件同事务提交；不硬删除原始来源记录。"""
    with factory.begin() as session:
        row = session.scalar(select(Evidence).where(Evidence.id == evidence_id).with_for_update())
        if row is None:
            raise ValueError("证据不存在")
        state = session.get(EvidenceState, evidence_id)
        if state is None:
            state = EvidenceState(evidence_id=evidence_id, active=True, generation=1)
            session.add(state)
        state.generation += 1
        state.active = not delete
        if content is not None:
            if not content.strip():
                raise ValueError("正文不能为空")
            row.text = content
            row.content_hash = digest({"text": content, "payload": row.payload})
            row.content_version = f"revision-{state.generation}"
        session.add(IndexEvent(id=str(uuid4()), evidence_id=evidence_id))


def sync_events(factory, settings, limit=100, repository=EvidenceVectors) -> dict:
    """按证据行锁串行化，同步最新状态而非事件携带的旧正文。"""
    succeeded, failed = 0, 0
    with factory() as session:
        ids = list(session.scalars(
            select(IndexEvent.id).where(
                IndexEvent.status == "pending",
                (IndexEvent.retry_at.is_(None)) | (IndexEvent.retry_at <= datetime.now(UTC)),
            ).order_by(IndexEvent.created_at).limit(limit)
        ))
    for event_id in ids:
        try:
            with factory.begin() as session:
                event = session.scalar(
                    select(IndexEvent).where(IndexEvent.id == event_id).with_for_update()
                )
                if event.status != "pending":
                    continue
                row = session.scalar(
                    select(Evidence).where(Evidence.id == event.evidence_id).with_for_update()
                )
                state = session.get(EvidenceState, event.evidence_id)
                manifests = session.scalars(
                    select(VectorManifest).where(VectorManifest.evidence_id == event.evidence_id)
                ).all()
                if row is None or (state and not state.active):
                    with repository(settings, row.evidence_kind if row else "rule") as vectors:
                        for manifest in manifests:
                            vectors.delete([manifest.chunk_id], manifest.collection)
                            session.delete(manifest)
                else:
                    with repository(settings, row.evidence_kind) as vectors:
                        previous = next(
                            (m for m in manifests if m.collection == vectors.collection), None,
                        )
                        # 每条事件都执行 upsert，故集合丢失后 rebuild 仍能重建。
                        embedding = EmbeddingService(settings).embed_one(row.text)
                        chunk_id = vectors.upsert({
                            "id": row.id, "market": row.market, "category": row.category,
                            "product_id": row.product_id, "content_hash": row.content_hash,
                        }, embedding)
                        if previous:
                            if previous.chunk_id != chunk_id:
                                vectors.delete([previous.chunk_id])
                            previous.chunk_id = chunk_id
                            previous.content_hash = row.content_hash
                        else:
                            session.add(VectorManifest(
                                evidence_id=row.id, collection=vectors.collection,
                                chunk_id=chunk_id, content_hash=row.content_hash,
                            ))
                event.status = "done"
                event.error = None
                succeeded += 1
        except Exception as error:
            # 向量写成功但 PG 提交失败时，相同 chunk_id 重放不能生成重复主键。
            with factory.begin() as session:
                event = session.get(IndexEvent, event_id)
                event.attempts += 1
                event.error = type(error).__name__
                event.status = "failed" if event.attempts >= 5 else "pending"
                event.retry_at = datetime.now(UTC) + timedelta(seconds=2 ** event.attempts)
            failed += 1
    return {"done": succeeded, "failed": failed}
