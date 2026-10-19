"""嵌入服务的离线单元测试。"""

from app.core.config import Settings
from app.core.embeddings import EmbeddingService


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
