"""Milvus 规则向量集合的创建、写入和检索实现。"""

import hashlib
import logging
from dataclasses import dataclass

from pymilvus import DataType, MilvusClient

from app.core.config import Settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RuleVector:
    """写入 Milvus 前的规则证据向量载荷。"""

    evidence_id: str
    market: str
    category: str
    content: str
    embedding: list[float]


class MilvusRuleRepository:
    """管理版本化规则集合；原文与最终有效性仍以 PostgreSQL 为准。"""

    def __init__(self, settings: Settings) -> None:
        """保存连接配置，并按向量空间生成独立、稳定的集合名称。"""
        self.settings = settings
        # 模型或维度变更时使用新集合，避免不同向量空间发生混检索。
        vector_space = (
            f"{settings.embedding_provider}:{settings.embedding_model or 'offline'}:"
            f"{settings.embedding_dim}"
        )
        suffix = hashlib.sha256(vector_space.encode("utf-8")).hexdigest()[:12]
        self.collection_name = f"rule_chunks_v1_{suffix}"
        self._client_instance: MilvusClient | None = None

    def _client(self) -> MilvusClient:
        """按仓储实例复用 MilvusClient，避免旧 ORM Collection 接口的运行警告。"""
        if self._client_instance is None:
            logger.debug("连接 Milvus | uri=%s", self.settings.milvus_uri)
            self._client_instance = MilvusClient(uri=self.settings.milvus_uri,
                                                 db_name=self.settings.milvus_database)
        return self._client_instance

    def _ensure_collection(self) -> MilvusClient:
        """获取规则集合；首次运行时创建 Schema 和 HNSW 索引。"""
        client = self._client()
        if not client.has_collection(self.collection_name):
            logger.info("创建 Milvus 集合 | collection=%s", self.collection_name)
            schema = MilvusClient.create_schema(auto_id=False, enable_dynamic_field=False)
            schema.add_field(
                field_name="evidence_id",
                datatype=DataType.VARCHAR,
                is_primary=True,
                max_length=80,
            )
            schema.add_field(field_name="market", datatype=DataType.VARCHAR, max_length=12)
            schema.add_field(field_name="category", datatype=DataType.VARCHAR, max_length=120)
            schema.add_field(field_name="content", datatype=DataType.VARCHAR, max_length=8192)
            schema.add_field(
                field_name="embedding",
                datatype=DataType.FLOAT_VECTOR,
                dim=self.settings.embedding_dim,
            )
            index_params = client.prepare_index_params()
            index_params.add_index(
                field_name="embedding",
                metric_type="COSINE",
                index_type="HNSW",
                params={"M": 8, "efConstruction": 64},
            )
            client.create_collection(
                collection_name=self.collection_name,
                schema=schema,
                index_params=index_params,
            )
        else:
            logger.debug("复用 Milvus 集合 | collection=%s", self.collection_name)
        client.load_collection(collection_name=self.collection_name)
        return client

    def upsert(self, records: list[RuleVector]) -> int:
        """按稳定 evidence_id 幂等写入规则向量，并刷新后返回记录数。"""
        if not records:
            return 0
        client = self._ensure_collection()
        client.upsert(
            collection_name=self.collection_name,
            data=[
                {
                    "evidence_id": item.evidence_id,
                    "market": item.market,
                    "category": item.category,
                    "content": item.content,
                    "embedding": item.embedding,
                }
                for item in records
            ],
        )
        client.flush(collection_name=self.collection_name)
        logger.info("规则向量已写入 | collection=%s records=%d", self.collection_name, len(records))
        logger.debug("写入证据样例 | evidence_ids=%s", [item.evidence_id for item in records[:3]])
        return len(records)

    def search(self, embedding: list[float], market: str, top_k: int) -> list[dict]:
        """按市场做向量召回；调用方必须回查 PostgreSQL 后再对外返回。"""
        client = self._ensure_collection()
        safe_market = market.replace("\\", "\\\\").replace('"', '\\"')
        result = client.search(
            collection_name=self.collection_name,
            data=[embedding],
            anns_field="embedding",
            search_params={"metric_type": "COSINE", "params": {"ef": 64}},
            limit=top_k,
            filter=f'market == "{safe_market}"',
            output_fields=["market", "category", "content"],
        )
        hits = []
        for hit in result[0]:
            # MilvusClient 会使用 Schema 中的主键名（这里是 evidence_id），不会统一返回 id。
            # 同时兼容 SDK 的 Hit 对象及文档中描述的普通字典返回值。
            evidence_id = hit.get("evidence_id") or getattr(hit, "id", None)
            entity = hit.get("entity", {})
            hits.append(
                {
                    "evidence_id": evidence_id,
                    "score": round(float(hit["distance"]), 6),
                    "market": entity.get("market"),
                    "category": entity.get("category"),
                    "content": entity.get("content"),
                }
            )
        logger.info("规则向量检索完成 | market=%s requested=%d hits=%d", market, top_k, len(hits))
        logger.debug(
            "检索命中样例 | hits=%s",
            [{"evidence_id": hit["evidence_id"], "score": hit["score"]} for hit in hits[:3]],
        )
        return hits
