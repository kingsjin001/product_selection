"""规则证据服务：编排数据库、向量生成和 Milvus 检索。"""

import logging

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.embeddings import EmbeddingService
from app.repositories.evidence import get_evidence_by_ids, list_evidence
from app.repositories.milvus import MilvusRuleRepository, RuleVector

logger = logging.getLogger(__name__)


def index_rule_evidence(session: Session, settings: Settings) -> dict:
    """将当前规则证据转为向量，并写入带版本的 Milvus 集合。"""
    rules = list_evidence(session, evidence_kind="rule")
    logger.info(
        "开始索引规则证据 | records=%d provider=%s", len(rules), settings.embedding_provider
    )
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
    result = {
        "status": "indexed",
        "collection": repository.collection_name,
        "embedding_provider": settings.embedding_provider,
        "embedding_model": settings.embedding_model,
        "embedding_dimension": settings.embedding_dim,
        "records": count,
    }
    logger.info("规则证据索引完成 | collection=%s records=%d", repository.collection_name, count)
    logger.debug("索引证据样例 | evidence_ids=%s", [item.id for item in rules[:3]])
    return result


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
        logger.warning("规则检索被拒绝：查询为空")
        return {"status": "invalid_request", "data": [], "warnings": ["query must not be blank"]}
    if not 1 <= top_k <= 10:
        logger.warning("规则检索被拒绝：top_k 超出范围 | top_k=%d", top_k)
        return {
            "status": "invalid_request",
            "data": [],
            "warnings": ["top_k must be between 1 and 10"],
        }

    logger.info("开始规则检索 | market=%s top_k=%d", market, top_k)
    logger.debug("检索查询样例 | query=%r", query[:120])
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
    result = {
        "status": "ok" if data else "no_results",
        "data": data,
        "evidence_ids": [item["evidence_id"] for item in data],
        "warnings": [] if data else ["No indexed rule evidence matched this request."],
    }
    logger.info("规则检索结束 | status=%s results=%d", result["status"], len(data))
    logger.debug("最终证据样例 | evidence_ids=%s", result["evidence_ids"][:3])
    return result
