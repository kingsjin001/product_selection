"""Evidence 表的只读查询函数。"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Evidence


def list_evidence(
    session: Session,
    *,
    evidence_kind: str,
    market: str | None = None,
    category: str | None = None,
) -> list[Evidence]:
    """按证据类型与可选市场、品类条件列出证据。"""
    query = select(Evidence).where(Evidence.evidence_kind == evidence_kind)
    if market:
        query = query.where(Evidence.market == market)
    if category:
        query = query.where(Evidence.category == category)
    return list(session.scalars(query.order_by(Evidence.id)))


def get_evidence_by_ids(session: Session, ids: list[str]) -> list[Evidence]:
    """批量读取指定证据，供向量检索结果回查和有效性确认使用。"""
    if not ids:
        return []
    return list(session.scalars(select(Evidence).where(Evidence.id.in_(ids))))
