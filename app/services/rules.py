"""规则证据服务：编排数据库、向量生成和 Milvus 检索。"""

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.embeddings import EmbeddingService
from app.repositories.evidence import get_evidence_by_ids, list_evidence
from app.repositories.milvus import MilvusRuleRepository, RuleVector


def index_rule_evidence(session: Session, settings: Settings) -> dict:
    """将当前规则证据转为向量，并写入带版本的 Milvus 集合。"""
    rules = list_evidence(session, evidence_kind="rule")
    embedder = EmbeddingService(settings)
    # 先生成全部向量，再用严格 zip 防止证据与向量错位。
    vectors = embedder.embed_many([item.text for item in rules])
    repository = MilvusRuleRepository(settings)
    count = repository.upsert(
        [
            RuleVector(
                evidence_id=item.id,
                market=item.market,
                category=item.category,
                content=item.text,
                embedding=vector,
            )
            for item, vector in zip(rules, vectors, strict=True)
        ]
    )
    return {
        "status": "indexed",
        "collection": repository.collection_name,
        "embedding_provider": settings.embedding_provider,
        "embedding_model": settings.embedding_model,
        "embedding_dimension": settings.embedding_dim,
        "records": count,
    }


def search_rules(
    session: Session,
    settings: Settings,
    *,
    query: str,
    market: str,
    top_k: int = 3,
) -> dict:
    """按市场检索规则证据，并将向量命中恢复为可追溯业务字段。"""
    if not query.strip():
        return {"status": "invalid_request", "data": [], "warnings": ["query must not be blank"]}
    if not 1 <= top_k <= 10:
        return {
            "status": "invalid_request",
            "data": [],
            "warnings": ["top_k must be between 1 and 10"],
        }

    embedding = EmbeddingService(settings).embed_one(query)
    candidates = MilvusRuleRepository(settings).search(embedding, market=market, top_k=top_k)
    # Milvus 仅保存检索字段，原始证据仍以 PostgreSQL 为准。
    evidence_by_id = {
        item.id: item
        for item in get_evidence_by_ids(session, [item["evidence_id"] for item in candidates])
    }
    data = []
    for candidate in candidates:
        evidence = evidence_by_id.get(candidate["evidence_id"])
        if not evidence:
            continue
        data.append(
            {
                "evidence_id": evidence.id,
                "title": evidence.payload.get("title"),
                "snippet": evidence.text[:500],
                "score": candidate["score"],
                "source_url": evidence.source_url,
                "observed_at": evidence.observed_at.isoformat() if evidence.observed_at else None,
                "version": evidence.content_version,
            }
        )
    return {
        "status": "ok" if data else "no_results",
        "data": data,
        "evidence_ids": [item["evidence_id"] for item in data],
        "warnings": [] if data else ["No indexed rule evidence matched this request."],
    }
