"""MilvusClient 仓储适配测试，不依赖本机 Milvus 服务。"""

from pymilvus.client.search_result import Hit

from app.core.config import Settings
from app.repositories.milvus import MilvusRuleRepository, RuleVector


class _FakeSchema:
    """记录创建集合时声明的字段，供断言使用。"""

    def __init__(self) -> None:
        self.fields: list[dict] = []

    def add_field(self, **kwargs) -> None:
        """记录一次字段定义。"""
        self.fields.append(kwargs)


class _FakeIndexParams:
    """记录创建集合时声明的向量索引。"""

    def __init__(self) -> None:
        self.indexes: list[dict] = []

    def add_index(self, **kwargs) -> None:
        """记录一次索引定义。"""
        self.indexes.append(kwargs)


class _FakeMilvusClient:
    """模拟 MilvusClient 的最小公开接口，验证请求载荷而非 SDK 内部行为。"""

    instance: "_FakeMilvusClient | None" = None

    def __init__(self, uri: str, db_name: str = "default") -> None:
        self.uri = uri
        self.db_name = db_name
        self.created: dict | None = None
        self.loaded: list[str] = []
        self.upserts: list[dict] = []
        self.flushed: list[str] = []
        self.search_request: dict | None = None
        _FakeMilvusClient.instance = self

    @staticmethod
    def create_schema(**kwargs) -> _FakeSchema:
        """返回可记录字段的伪 Schema。"""
        return _FakeSchema()

    def has_collection(self, collection_name: str) -> bool:
        """首次访问模拟为集合不存在。"""
        return False

    def prepare_index_params(self) -> _FakeIndexParams:
        """返回可记录索引的伪参数对象。"""
        return _FakeIndexParams()

    def create_collection(self, **kwargs) -> None:
        """记录创建集合请求。"""
        self.created = kwargs

    def load_collection(self, *, collection_name: str) -> None:
        """记录加载集合请求。"""
        self.loaded.append(collection_name)

    def upsert(self, **kwargs) -> None:
        """记录写入请求。"""
        self.upserts.append(kwargs)

    def flush(self, *, collection_name: str) -> None:
        """记录刷新请求。"""
        self.flushed.append(collection_name)

    def search(self, **kwargs) -> list[list[dict]]:
        """返回当前 PyMilvus 实际使用的 Hit 对象，主键名与 Schema 保持一致。"""
        self.search_request = kwargs
        return [
            [
                Hit(
                    {
                        "evidence_id": "ev-rule-001",
                        "distance": 0.91,
                        "entity": {
                            "market": "US",
                            "category": "kitchen",
                            "content": "food-contact rule",
                        },
                    },
                    pk_name="evidence_id",
                )
            ]
        ]


def test_milvus_client_creates_and_queries_collection(monkeypatch) -> None:
    """仓储应通过 MilvusClient 创建、写入、刷新并解析检索结果。"""
    monkeypatch.setattr("app.repositories.milvus.MilvusClient", _FakeMilvusClient)
    repository = MilvusRuleRepository(Settings(embedding_provider="mock", embedding_dim=2))

    inserted = repository.upsert(
        [
            RuleVector(
                evidence_id="ev-rule-001",
                market="US",
                category="kitchen",
                content="food-contact rule",
                embedding=[1.0, 0.0],
            )
        ]
    )
    hits = repository.search([1.0, 0.0], market="US", top_k=3)

    client = _FakeMilvusClient.instance
    assert client is not None
    assert inserted == 1
    assert client.uri == "http://localhost:19530"
    assert client.created is not None
    assert client.created["collection_name"] == repository.collection_name
    assert client.created["schema"].fields[0]["field_name"] == "evidence_id"
    assert client.upserts[0]["data"][0]["evidence_id"] == "ev-rule-001"
    assert client.flushed == [repository.collection_name]
    assert client.search_request is not None
    assert client.search_request["filter"] == 'market == "US"'
    assert hits == [
        {
            "evidence_id": "ev-rule-001",
            "score": 0.91,
            "market": "US",
            "category": "kitchen",
            "content": "food-contact rule",
        }
    ]
