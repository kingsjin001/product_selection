"""版本有效性回查与关键词/向量 RRF 融合。"""

import re

from sqlalchemy import select

from app.core.embeddings import EmbeddingService
from app.db.index_models import EvidenceState
from app.db.models import Evidence
from app.repositories.vectors import EvidenceVectors


def tokens(value: str) -> set[str]:
    """中英文轻量分词：英文单词、中文二元字组，作为关键词基线。"""
    words = set(re.findall(r"[a-z0-9]+", value.lower()))
    for segment in re.findall(r"[\u4e00-\u9fff]+", value):
        words.update(segment[i:i + 2] for i in range(max(1, len(segment) - 1)))
    return words


def reciprocal_rank_fusion(dense: list[str], lexical: list[str], k=60) -> list[str]:
    """按排名融合去重，不直接相加不同意义的分数。"""
    scores = {}
    for ranking in (dense, lexical):
        for rank, identity in enumerate(dict.fromkeys(ranking), 1):
            scores[identity] = scores.get(identity, 0) + 1 / (k + rank)
    return sorted(scores, key=lambda item: (-scores[item], item))


def search_evidence(factory, settings, *, query, market, kind, category="", product_id="",
                    top_k=5, snapshot=None, repository=EvidenceVectors, as_of=None,
                    diagnostics=None):
    """只返回当前有效且版本相符的证据，可进一步限制到冻结快照。"""
    if not query.strip() or not 1 <= top_k <= 20:
        raise ValueError("查询不能为空，top_k 必须为 1～20")
    with factory() as session:
        statement = select(Evidence).outerjoin(
            EvidenceState, Evidence.id == EvidenceState.evidence_id,
        ).where(
            Evidence.evidence_kind == kind, Evidence.market == market,
            (EvidenceState.active.is_(True)) | (EvidenceState.evidence_id.is_(None)),
        )
        if category:
            statement = statement.where(Evidence.category.in_([category, "all"]))
        if product_id:
            statement = statement.where(Evidence.product_id == product_id)
        if as_of:
            statement = statement.where(Evidence.observed_at <= as_of)
        rows = session.scalars(statement).all()
        allowed = {
            row.id: {"id": row.id, "text": row.text, "content_hash": row.content_hash,
                     "version": row.content_version, "source_url": row.source_url,
                     "market": row.market, "category": row.category}
            for row in rows
        }
    if snapshot is not None:
        frozen = {row["id"]: row for row in snapshot["evidence"]}
        allowed = {
            identity: frozen[identity] for identity, row in allowed.items()
            if identity in frozen and row["content_hash"] == frozen[identity]["content_hash"]
        }
    query_tokens = tokens(query)
    ranked = sorted(
        ((len(query_tokens & tokens(row["text"])), identity) for identity, row in allowed.items()),
        key=lambda item: (-item[0], item[1]),
    )
    lexical = [identity for count, identity in ranked if count]
    vector = EmbeddingService(settings).embed_one(query)
    with repository(settings, kind) as vectors:
        hits = vectors.search(vector, market, category, product_id, limit=max(20, top_k * 3))
    dense = [
        hit["evidence_id"] for hit in hits
        if hit["evidence_id"] in allowed
        and allowed[hit["evidence_id"]]["content_hash"] == hit["content_hash"]
    ]
    fused = reciprocal_rank_fusion(dense, lexical)
    if diagnostics is not None:
        diagnostics.update(dense=dense, lexical=lexical, rrf=fused)
    return [allowed[identity] for identity in fused[:top_k]]
