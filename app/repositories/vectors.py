"""版本化向量仓储：规则/评论分集合，稳定版本主键与强一致检索。"""

import hashlib
import json

from pymilvus import DataType, MilvusClient


def vector_identity(settings, kind: str) -> str:
    """向量空间包含模型、维度和预处理版本，避免同维度模型混用。"""
    source = f"{settings.embedding_provider}:{settings.embedding_model}:{settings.embedding_dim}:v3"
    return f"{kind}_chunks_v3_{hashlib.sha256(source.encode()).hexdigest()[:12]}"


def chunk_identity(evidence_id: str, content_hash: str) -> str:
    """每个证据版本生成独立主键，迟到写入不能覆盖新版本。"""
    return hashlib.sha256(f"{evidence_id}:{content_hash}".encode()).hexdigest()


class EvidenceVectors:
    """只管理向量，最终版本与有效性仍由 PostgreSQL 回查。"""

    def __init__(self, settings, kind: str):
        """创建客户端和集合名，连接生命周期由上下文管理器负责。"""
        if kind not in ("rule", "review"):
            raise ValueError("只支持 rule/review 集合")
        self.settings = settings
        self.collection = vector_identity(settings, kind)
        self.client = MilvusClient(uri=settings.milvus_uri, db_name=settings.milvus_database,
                                   timeout=15)

    def __enter__(self):
        """进入仓储上下文。"""
        return self

    def __exit__(self, *_args):
        """操作结束释放客户端连接。"""
        self.client.close()

    def ensure(self):
        """创建显式 Schema 和 HNSW 索引，首次初始化后加载集合。"""
        if not self.client.has_collection(self.collection):
            schema = MilvusClient.create_schema(auto_id=False, enable_dynamic_field=False)
            for name, size in (
                ("chunk_id", 64), ("evidence_id", 80), ("content_hash", 64),
                ("market", 12), ("category", 120), ("product_id", 80),
            ):
                schema.add_field(
                    name, DataType.VARCHAR, max_length=size, is_primary=name == "chunk_id",
                )
            schema.add_field("embedding", DataType.FLOAT_VECTOR, dim=self.settings.embedding_dim)
            params = self.client.prepare_index_params()
            params.add_index("embedding", index_type="HNSW", metric_type="COSINE",
                             params={"M": 8, "efConstruction": 64})
            self.client.create_collection(self.collection, schema=schema, index_params=params,
                                          consistency_level="Strong")
        self.client.load_collection(self.collection)

    def upsert(self, row: dict, vector: list[float]) -> str:
        """写入单条版本记录，返回稳定主键供 manifest 保存。"""
        self.ensure()
        chunk_id = chunk_identity(row["id"], row["content_hash"])
        self.client.upsert(self.collection, [{
            "chunk_id": chunk_id, "evidence_id": row["id"], "content_hash": row["content_hash"],
            "market": row["market"], "category": row["category"],
            "product_id": row.get("product_id") or "", "embedding": vector,
        }])
        return chunk_id

    def delete(self, chunk_ids: list[str], collection: str | None = None):
        """清理指定集合中已知的旧版本；不存在集合时视为已完成。"""
        target = collection or self.collection
        if chunk_ids and self.client.has_collection(target):
            self.client.delete(target, ids=chunk_ids)

    def search(self, vector, market: str, category: str = "", product_id: str = "", limit=20):
        """标量过滤先于向量召回；JSON 转义防止过滤字符串注入。"""
        if not self.client.has_collection(self.collection):
            raise RuntimeError("第三期向量集合尚未建立，请先执行索引同步")
        filters = [f"market == {json.dumps(market)}"]
        if category:
            filters.append(f"category in [{json.dumps(category)}, \"all\"]")
        if product_id:
            filters.append(f"product_id == {json.dumps(product_id)}")
        result = self.client.search(
            self.collection, data=[vector], anns_field="embedding", limit=limit,
            filter=" and ".join(filters), output_fields=["evidence_id", "content_hash"],
            search_params={"metric_type": "COSINE", "params": {"ef": 64}},
            consistency_level="Strong",
        )
        return [item["entity"] for item in result[0]]
