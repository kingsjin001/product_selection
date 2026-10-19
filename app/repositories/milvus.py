"""Milvus 规则向量集合的创建、写入和检索实现。"""

from dataclasses import dataclass

from pymilvus import Collection, CollectionSchema, DataType, FieldSchema, connections, utility

from app.core.config import Settings


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

    collection_name = "rule_chunks_v1"

    def __init__(self, settings: Settings) -> None:
        """保存连接配置，延迟到首次使用时连接 Milvus。"""
        self.settings = settings
        self._connected = False

    def _connect(self) -> None:
        """复用默认别名连接，避免一个仓储实例重复建立连接。"""
        if not self._connected:
            connections.connect(
                alias="default", host=self.settings.milvus_host, port=str(self.settings.milvus_port)
            )
            self._connected = True

    def _collection(self) -> Collection:
        """获取规则集合；首次运行时创建 Schema 和 HNSW 索引。"""
        self._connect()
        if not utility.has_collection(self.collection_name):
            fields = [
                FieldSchema(
                    name="evidence_id",
                    dtype=DataType.VARCHAR,
                    is_primary=True,
                    auto_id=False,
                    max_length=80,
                ),
                FieldSchema(name="market", dtype=DataType.VARCHAR, max_length=12),
                FieldSchema(name="category", dtype=DataType.VARCHAR, max_length=120),
                FieldSchema(name="content", dtype=DataType.VARCHAR, max_length=8192),
                FieldSchema(
                    name="embedding", dtype=DataType.FLOAT_VECTOR, dim=self.settings.embedding_dim
                ),
            ]
            schema = CollectionSchema(fields=fields, description="Versioned rule evidence chunks")
            collection = Collection(self.collection_name, schema=schema)
            collection.create_index(
                field_name="embedding",
                index_params={
                    "metric_type": "COSINE",
                    "index_type": "HNSW",
                    "params": {"M": 8, "efConstruction": 64},
                },
            )
        else:
            collection = Collection(self.collection_name)
        collection.load()
        return collection

    def upsert(self, records: list[RuleVector]) -> int:
        """按稳定 evidence_id 幂等写入规则向量，并刷新后返回记录数。"""
        if not records:
            return 0
        collection = self._collection()
        collection.upsert(
            [
                [item.evidence_id for item in records],
                [item.market for item in records],
                [item.category for item in records],
                [item.content for item in records],
                [item.embedding for item in records],
            ]
        )
        collection.flush()
        return len(records)

    def search(self, embedding: list[float], market: str, top_k: int) -> list[dict]:
        """按市场做向量召回；调用方必须回查 PostgreSQL 后再对外返回。"""
        collection = self._collection()
        result = collection.search(
            data=[embedding],
            anns_field="embedding",
            param={"metric_type": "COSINE", "params": {"ef": 64}},
            limit=top_k,
            expr=f'market == "{market.replace(chr(34), "")}"',
            output_fields=["market", "category", "content"],
        )
        return [
            {
                "evidence_id": hit.id,
                "score": round(float(hit.score), 6),
                "market": hit.entity.get("market"),
                "category": hit.entity.get("category"),
                "content": hit.entity.get("content"),
            }
            for hit in result[0]
        ]
