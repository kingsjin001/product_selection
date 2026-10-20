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
    """按证据类型与可选市场、品类条件读取证据，供服务层组装业务结果。"""
    query = select(Evidence).where(Evidence.evidence_kind == evidence_kind)
    # 可选条件仅在传入时加入，保持一个函数覆盖导入、索引和检索回查。
    if market:
        query = query.where(Evidence.market == market)
    if category:
        query = query.where(Evidence.category == category)
    return list(session.scalars(query.order_by(Evidence.id)))


def get_evidence_by_ids(session: Session, ids: list[str]) -> list[Evidence]:
    """批量读取指定证据，供 Milvus 命中结果回查与有效性确认使用。"""
    if not ids:
        return []
    # 使用一次 IN 查询替代逐条读取，避免检索结果多时产生 N+1 查询。
    return list(session.scalars(select(Evidence).where(Evidence.id.in_(ids))))
