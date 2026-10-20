"""第四期任务幂等、租约隔离、取消与 outbox 故障测试。"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.analysis_contracts import AnalysisRequest
from app.api.tasks import event_stream
from app.core.config import Settings
from app.db.analysis_models import AnalysisReport
from app.db.models import Product
from app.db.session import Base
from app.db.task_models import Task, TaskDispatch
from app.services.analysis_store import AnalysisStore
from app.services.tasks import OwnershipLost, TaskConflict, TaskService
from app.workers.dispatcher import dispatch_once


@pytest.fixture
def tasks():
    """独立内存数据库验证事务逻辑，真实进程退出另由集成脚本覆盖。"""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory.begin() as session:
        session.add(Product(id="p", name="测试商品", market="US", category="home"))
    service = TaskService(factory, Settings(_env_file=None))
    yield service
    engine.dispose()


def create(tasks, key="key"):
    """建立固定流程任务，测试无需供应商凭据。"""
    return tasks.create(AnalysisRequest(product_id="p", mode="fixed"), key)


def test_idempotency_and_atomic_outbox(tasks):
    identity = create(tasks)
    assert create(tasks) == identity
    with pytest.raises(TaskConflict):
        tasks.create(AnalysisRequest(product_id="p", question="不同输入", mode="fixed"), "key")
    with tasks.factory() as session:
        assert len(session.scalars(select(TaskDispatch)).all()) == 1
    assert tasks.events(identity)[0]["type"] == "queued"


def test_duplicate_message_and_fencing(tasks):
    identity = create(tasks)
    epoch = tasks.claim(identity)
    assert tasks.claim(identity) is None
    with tasks.factory.begin() as session:
        session.get(Task, identity).lease_until = datetime.now(UTC) - timedelta(seconds=1)
    assert tasks.recover() == 1
    new_epoch = tasks.claim(identity)
    assert new_epoch > epoch
    with tasks.factory.begin() as session, pytest.raises(OwnershipLost):
        tasks.guard(session, identity, epoch)
    tasks.heartbeat(identity, new_epoch)
    tasks.fail(identity, epoch, RuntimeError())
    assert tasks.get(identity)["status"] == "running"


def test_cancel_late_result_cannot_publish(tasks):
    identity = create(tasks)
    epoch = tasks.claim(identity)
    tasks.cancel(identity)
    store = AnalysisStore(tasks.factory, tasks.settings)
    store.guard = lambda session: tasks.guard(session, identity, epoch)
    store.on_complete = lambda session: tasks.complete(session, identity, epoch)
    with pytest.raises(OwnershipLost):
        store.save_report(identity, {"evidence": [], "research": {"claims": []}}, "late")
    assert store.report(identity) is None
    tasks.fail(identity, epoch, OwnershipLost())
    assert tasks.get(identity)["status"] == "cancelled"


def test_report_completion_and_sse_replay(tasks):
    identity = create(tasks)
    epoch = tasks.claim(identity)
    store = AnalysisStore(tasks.factory, tasks.settings)
    store.guard = lambda session: tasks.guard(session, identity, epoch)
    store.on_complete = lambda session: tasks.complete(session, identity, epoch)
    report = {"evidence": [], "research": {"claims": []}}
    store.save_report(identity, report, "报告")
    assert tasks.get(identity)["status"] == "completed"
    assert tasks.events(identity)[-1]["type"] == "completed"
    with tasks.factory() as session:
        assert len(session.scalars(select(AnalysisReport)).all()) == 1
    replay = list(event_stream(tasks, identity, after=1))
    assert len(replay) == 2
    assert replay[0].startswith("id: 2\n") and replay[1].startswith("id: 3\n")


def test_dispatch_crash_between_send_and_commit(tasks):
    identity = create(tasks)
    sent = []

    def crash():
        raise RuntimeError("injected after broker send")

    assert dispatch_once(tasks.factory, sender=sent.append, after_send=crash) == 0
    with tasks.factory.begin() as session:
        row = session.scalar(select(TaskDispatch))
        assert row.status == "pending"
        row.retry_at = None
    assert dispatch_once(tasks.factory, sender=sent.append) == 1
    assert sent == [identity, identity]
    assert tasks.claim(identity)
    assert tasks.claim(identity) is None


def test_deadline_survives_recovery(tasks):
    identity = create(tasks)
    epoch = tasks.claim(identity)
    with tasks.factory.begin() as session:
        row = session.get(Task, identity)
        row.lease_until = row.deadline_at = datetime.now(UTC) - timedelta(seconds=1)
    tasks.recover()
    assert tasks.get(identity)["status"] == "failed"
    with pytest.raises(TaskConflict):
        tasks.resume(identity)
    with tasks.factory.begin() as session, pytest.raises(OwnershipLost):
        tasks.guard(session, identity, epoch)
