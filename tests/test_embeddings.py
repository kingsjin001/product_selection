"""嵌入服务的离线单元测试。"""

from types import SimpleNamespace

from app.core.config import Settings
from app.core.embeddings import EmbeddingService
from app.repositories.milvus import MilvusRuleRepository


def test_mock_embedding_is_stable_and_normalized() -> None:
    """相同文本应得到稳定且归一化的 mock 向量。"""
    service = EmbeddingService(Settings(embedding_provider="mock", embedding_dim=16))
    first = service.embed_one("food contact material")
    second = service.embed_one("food contact material")

    assert first == second
    assert len(first) == 16
    assert round(sum(value * value for value in first), 6) == 1.0


def test_mock_embedding_empty_text_is_zero_vector() -> None:
    """空文本不产生无效数值，返回全零向量。"""
    service = EmbeddingService(Settings(embedding_provider="mock", embedding_dim=8))
    assert service.embed_one("") == [0.0] * 8


def test_milvus_collection_name_changes_with_vector_space() -> None:
    """不同模型或维度必须写入独立集合，防止向量空间混用。"""
    offline = MilvusRuleRepository(Settings(embedding_provider="mock", embedding_dim=16))
    real = MilvusRuleRepository(
        Settings(
            embedding_provider="openai_compatible",
            embedding_model="demo-embedding",
            embedding_dim=1024,
        )
    )

    assert offline.collection_name.startswith("rule_chunks_v1_")
    assert offline.collection_name != real.collection_name


def test_openai_compatible_embeddings_are_requested_in_batches(monkeypatch) -> None:
    """真实向量服务有单批限制时，服务应保序地拆分输入文本。"""
    requests: list[list[str]] = []

    class FakeEmbeddings:
        """记录请求批次并返回固定二维向量。"""

        def create(self, **kwargs):
            batch = kwargs["input"]
            requests.append(batch)
            return SimpleNamespace(
                data=[
                    SimpleNamespace(embedding=[float(index), 1.0])
                    for index, _ in enumerate(batch)
                ]
            )

    class FakeOpenAI:
        """模拟 OpenAI 兼容客户端，避免测试访问网络。"""

        def __init__(self, **_kwargs) -> None:
            self.embeddings = FakeEmbeddings()

    monkeypatch.setattr("app.core.embeddings.OpenAI", FakeOpenAI)
    service = EmbeddingService(
        Settings(
            embedding_provider="openai_compatible",
            embedding_model="demo-embedding",
            embedding_dim=2,
            embedding_batch_size=2,
            model_api_key="test-key",
        )
    )

    vectors = service.embed_many(["一", "二", "三", "四", "五"])

    assert requests == [["一", "二"], ["三", "四"], ["五"]]
    assert len(vectors) == 5
    assert all(len(vector) == 2 for vector in vectors)
