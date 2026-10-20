"""第三期版本隔离、事件幂等和删除竞态回归。"""

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.db.index_models import EvidenceState, IndexEvent, VectorManifest
from app.db.models import Evidence, ImportBatch
from app.db.session import Base
from app.repositories.vectors import chunk_identity, vector_identity
from app.services.hybrid_search import reciprocal_rank_fusion, search_evidence
from app.services.indexing import change_evidence, enqueue_all, sync_events


class FakeVectors:
    """以内存字典模拟远端幂等主键与故障，测试不写用户 Milvus。"""

    rows = {}
    broken = False
    collection = "test-collection"

    def __init__(self, *args):
        """允许注入到生产同步服务。"""

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def upsert(self, row, embedding):
        """同一证据版本覆盖同一主键。"""
        if self.broken:
            raise RuntimeError("injected outage")
        key = chunk_identity(row["id"], row["content_hash"])
        self.rows[key] = row
        return key

    def delete(self, ids, collection=None):
        for key in ids:
            self.rows.pop(key, None)

    def search(self, *args, **kwargs):
        if self.broken:
            raise RuntimeError("injected unavailable")
        return [{"evidence_id": row["id"], "content_hash": row["content_hash"]}
                for row in self.rows.values()]


@pytest.fixture
def index_db():
    """每个测试创建独立数据库和两条冲突规格评论。"""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory.begin() as session:
        session.add(ImportBatch(id="b", manifest_hash="b", source_name="test"))
        session.flush()
        session.add(Evidence(
            id="e", import_batch_id="b", evidence_kind="review", source_type="test",
            source_record_id="e", market="US", category="home", content_hash="hash1",
            content_version="v1", text="大号漏水", payload={},
        ))
    FakeVectors.rows, FakeVectors.broken = {}, False
    yield factory, Settings(_env_file=None, embedding_provider="mock", embedding_dim=16)
    engine.dispose()


def test_rebuild_repeated_events_update_delete(index_db):
    """重复同步不增殖；丢失索引可重建；旧事件执行时读取最新正文。"""
    factory, settings = index_db
    enqueue_all(factory)
    enqueue_all(factory)
    assert sync_events(factory, settings, repository=FakeVectors)["done"] == 2
    assert len(FakeVectors.rows) == 1
    FakeVectors.rows.clear()
    enqueue_all(factory)
    sync_events(factory, settings, repository=FakeVectors)
    assert len(FakeVectors.rows) == 1
    change_evidence(factory, "e", content="小号密封正常")
    change_evidence(factory, "e", content="大号仍漏水")
    sync_events(factory, settings, repository=FakeVectors)
    assert len(FakeVectors.rows) == 1
    change_evidence(factory, "e", delete=True)
    # 清理向量之前就不能召回已删除证据。
    assert search_evidence(factory, settings, query="漏水", market="US", kind="review",
                           repository=FakeVectors) == []
    sync_events(factory, settings, repository=FakeVectors)
    assert not FakeVectors.rows
    with factory() as session:
        assert not session.get(EvidenceState, "e").active
        assert session.scalar(select(VectorManifest)) is None


def test_failed_event_is_retriable(index_db):
    """远端失败不能误标成功，错误只记录类型并使用退避。"""
    factory, settings = index_db
    enqueue_all(factory)
    FakeVectors.broken = True
    assert sync_events(factory, settings, repository=FakeVectors)["failed"] == 1
    with factory() as session:
        event = session.scalar(select(IndexEvent))
        assert event.status == "pending" and event.attempts == 1 and event.retry_at


def test_embedding_space_identity_and_rrf():
    """同维度不同模型也必须隔离，融合排名去重。"""
    first = Settings(_env_file=None, embedding_model="model-a")
    second = first.model_copy(update={"embedding_model": "model-b"})
    assert vector_identity(first, "rule") != vector_identity(second, "rule")
    assert vector_identity(first, "rule") != vector_identity(first, "review")
    assert reciprocal_rank_fusion(["a", "a", "b"], ["b", "c"]) == ["b", "a", "c"]


def test_vector_outage_is_not_empty_evidence(index_db):
    """Milvus 断连必须暴露故障，不能被当成没有风险证据。"""
    factory, settings = index_db
    FakeVectors.broken = True
    with pytest.raises(RuntimeError, match="unavailable"):
        search_evidence(factory, settings, query="漏水", market="US", kind="review",
                        repository=FakeVectors)
