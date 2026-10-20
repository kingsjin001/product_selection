"""第七期协议边界、原生技能、记忆隔离与人工复核的行为验收。"""

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from pydantic import SecretStr
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.agents.product_researcher import run_research
from app.analysis_contracts import AnalysisRequest
from app.core.config import Settings
from app.db.analysis_models import AnalysisCall, AnalysisRun
from app.db.interaction_models import ReportConversation, ReportReview
from app.db.models import Evidence
from app.db.session import Base
from app.db.task_models import Task, TaskDispatch
from app.ingestion.imports import ImportRequest, import_records
from app.mcp.context import scoped_snapshot, sign_context, verify_context
from app.services.analysis_store import AnalysisStore, RunBudget
from app.services.conversations import start_turn
from app.services.memory import (
    decide_candidate,
    preference_snapshot,
    propose_candidate,
    save_preferences,
)
from app.services.reports import ask_report, load_report
from app.services.reviews import decide_review, get_review, mark_waiting
from app.services.skills import FrozenSkillBackend, freeze_skills
from app.services.tasks import TaskConflict, TaskService
from app.workflows.analysis import build_workflow


@pytest.fixture
def env(tmp_path):
    """文件 SQLite 支持 Deep Agents 工具线程；不连接用户业务库。"""
    engine = create_engine(f"sqlite:///{tmp_path / 'phase7.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    settings = Settings(_env_file=None, mcp_shared_secret=SecretStr("test-only-" * 5))
    import_records(factory, ImportRequest.model_validate({
        "products": [{"product_id": "p", "product_name": "测试盒", "market": "US",
                      "category": "home"}],
        "reviews": [{"review_id": "r", "product_id": "p", "market": "US", "category": "home",
                     "rating": 2, "variant": "大号", "content": "大号盒渗漏",
                     "observed_at": "2026-10-01T00:00:00Z", "data_kind": "synthetic"}],
    }))
    yield factory, settings
    engine.dispose()


def paused(env):
    """运行原生图至 interrupt 后模拟 Worker 释放租约。"""
    factory, settings = env
    tasks = TaskService(factory, settings)
    identity = tasks.create(AnalysisRequest(product_id="p", mode="fixed",
                                           review_policy="always"), "review")
    epoch = tasks.claim(identity)
    store = AnalysisStore(factory, settings)
    store.guard = lambda session: tasks.guard(session, identity, epoch)
    store.on_complete = lambda session: tasks.complete(session, identity, epoch)
    store.status(identity, "running")
    saver = InMemorySaver()
    graph = build_workflow(store, identity, saver)
    config = {"configurable": {"thread_id": identity}}
    result = graph.invoke({"run_id": identity}, config)
    assert result["__interrupt__"]
    mark_waiting(store, identity)
    return tasks, store, identity, saver, config


def published(env):
    """创建固定报告，供会话测试使用。"""
    factory, settings = env
    store = AnalysisStore(factory, settings)
    identity = store.create(AnalysisRequest(product_id="p", mode="fixed"))
    build_workflow(store, identity, InMemorySaver()).invoke(
        {"run_id": identity}, {"configurable": {"thread_id": identity}})
    return identity


def test_review_pause_approval_and_budget_survive_wait(env):
    tasks, store, identity, saver, config = paused(env)
    assert tasks.get(identity)["status"] == "waiting_for_review"
    assert store.report(identity) is None and tasks.recover() == 0
    # 中断落盘后清理连接失败也不能把已释放的等待任务改成失败。
    tasks.fail(identity, tasks.get(identity)["epoch"], ConnectionError())
    assert tasks.get(identity)["status"] == "waiting_for_review"
    review = get_review(tasks.factory, identity)
    with tasks.factory.begin() as session:
        row = session.get(ReportReview, identity)
        row.waiting_at = datetime.now(UTC) - timedelta(days=2)
        session.get(AnalysisRun, identity).tool_calls = 3
    decide_review(tasks.factory, tasks.settings, identity, review["draft_hash"], "approve")
    decide_review(tasks.factory, tasks.settings, identity, review["draft_hash"], "approve")
    with tasks.factory() as session:
        assert len(session.scalars(select(TaskDispatch)).all()) == 2
    epoch = tasks.claim(identity)
    store.guard = lambda session: tasks.guard(session, identity, epoch)
    store.on_complete = lambda session: tasks.complete(session, identity, epoch)
    assert store.get(identity)["usage"]["tool_calls"] == 3
    assert tasks.get(identity)["attempts"] == 1
    graph = build_workflow(store, identity, saver)
    graph.invoke(Command(resume={"action": "approve", "feedback": ""}), config)
    assert store.report(identity) and tasks.get(identity)["status"] == "completed"


@pytest.mark.parametrize("action", ["reject", "cancel"])
def test_rejected_or_cancelled_review_cannot_publish(env, action):
    tasks, store, identity, _, _ = paused(env)
    review = get_review(tasks.factory, identity)
    if action == "cancel":
        tasks.cancel(identity)
    else:
        decide_review(tasks.factory, tasks.settings, identity, review["draft_hash"], "reject")
    with pytest.raises(TaskConflict):
        decide_review(tasks.factory, tasks.settings, identity, review["draft_hash"], "approve")
    assert tasks.get(identity)["status"] == "cancelled"
    assert store.report(identity) is None


def test_stale_review_and_revision_idempotency(env):
    tasks, store, identity, _, _ = paused(env)
    review = get_review(tasks.factory, identity)
    with pytest.raises(TaskConflict):
        decide_review(tasks.factory, tasks.settings, identity, "0" * 64, "approve")
    result = decide_review(tasks.factory, tasks.settings, identity, review["draft_hash"],
                            "request_changes", "补充说明规格差异")
    again = decide_review(tasks.factory, tasks.settings, identity, review["draft_hash"],
                           "request_changes", "补充说明规格差异")
    assert again == result
    child = store.get(result["revision_task_id"])
    assert child["versions"]["parent_run_id"] == identity
    assert child["snapshot"] == store.get(identity)["snapshot"]
    assert child["request"]["review_policy"] == "always"


def test_approval_does_not_bypass_changed_evidence(env):
    tasks, store, identity, saver, config = paused(env)
    review = get_review(tasks.factory, identity)
    decide_review(tasks.factory, tasks.settings, identity, review["draft_hash"], "approve")
    epoch = tasks.claim(identity)
    store.guard = lambda session: tasks.guard(session, identity, epoch)
    with tasks.factory.begin() as session:
        session.get(Evidence, "ev-review-r").content_hash = "changed"
    with pytest.raises(ValueError, match="证据已经更新"):
        build_workflow(store, identity, saver).invoke(
            Command(resume={"action": "approve", "feedback": ""}), config)
    assert store.report(identity) is None


def test_crash_after_interrupt_checkpoint_before_waiting_state(env):
    """检查点已中断而任务表仍运行时，租约恢复不能重新调用研究模型。"""
    from app.workflows.analysis import fixed_research

    factory, settings = env
    tasks = TaskService(factory, settings)
    identity = tasks.create(AnalysisRequest(product_id="p", mode="fixed",
                                           review_policy="always"), "crash-window")
    epoch = tasks.claim(identity)
    store = AnalysisStore(factory, settings)
    store.guard = lambda session: tasks.guard(session, identity, epoch)
    store.status(identity, "running")
    calls = []

    def researcher(request, snapshot, budget):
        """计数代替真实模型，判断恢复是否重做已完成研究。"""
        calls.append(request.product_id)
        return fixed_research(snapshot)

    saver = InMemorySaver()
    config = {"configurable": {"thread_id": identity}}
    result = build_workflow(store, identity, saver, researcher).invoke({"run_id": identity}, config)
    assert result["__interrupt__"]
    # 模拟进程在 mark_waiting 前退出，租约到期由 Dispatcher 发现。
    with factory.begin() as session:
        session.get(Task, identity).lease_until = datetime.now(UTC) - timedelta(seconds=1)
    assert tasks.recover() == 1
    epoch = tasks.claim(identity)
    store.status(identity, "running")
    restored = build_workflow(store, identity, saver, researcher).invoke(None, config)
    assert restored["__interrupt__"] and calls == ["p"]
    mark_waiting(store, identity)
    assert tasks.get(identity)["status"] == "waiting_for_review"


def test_mcp_signed_scope_rejects_tamper_cancel_and_old_epoch(env):
    factory, settings = env
    tasks = TaskService(factory, settings)
    identity = tasks.create(AnalysisRequest(product_id="p", mode="fixed"), "mcp")
    settings.agent_timeout_seconds = 3600
    epoch = tasks.claim(identity)
    with factory() as session:
        deadline = session.get(Task, identity).deadline_at.replace(tzinfo=UTC)
        assert 290 < (deadline - datetime.now(UTC)).total_seconds() <= 300
    store = AnalysisStore(factory, settings)
    store.status(identity, "running")
    token = sign_context(settings, store.get(identity), epoch)
    context = verify_context(settings, token)
    assert scoped_snapshot(factory, context)["product"]["id"] == "p"
    with pytest.raises(PermissionError):
        verify_context(settings, token + "a")
    with pytest.raises(PermissionError):
        scoped_snapshot(factory, {**context, "epoch": epoch - 1})
    tasks.cancel(identity)
    with pytest.raises(PermissionError):
        scoped_snapshot(factory, context)


def test_preference_candidates_confirm_edit_delete_and_freeze(env):
    factory, settings = env
    with factory.begin() as session:
        identity = propose_candidate(session, "source", {"target_market": "US"}, "我关注美国")
        assert preference_snapshot(session)["version"] == 0
    decide_candidate(factory, identity, "confirm", {"target_market": "GB"})
    store = AnalysisStore(factory, settings)
    run = store.create(AnalysisRequest(product_id="p", mode="fixed"))
    with factory.begin() as session:
        save_preferences(session, {})
    assert store.get(run)["versions"]["preferences"]["content"]["target_market"] == "GB"
    with pytest.raises(ValueError):
        decide_candidate(factory, identity, "ignore")


def test_conversation_history_is_used_and_report_is_immutable(env, monkeypatch):
    factory, settings = env
    identity = published(env)
    original = load_report(factory, identity)
    first = ask_report(factory, settings, identity, "大号的问题是什么")
    seen = {}

    class Model:
        """捕获实际构造的模型上下文，验证上一轮被带入。"""
        def bind(self, **kwargs):
            return self

        def invoke(self, messages):
            seen.update(json.loads(messages[1][1]))
            return SimpleNamespace(content=json.dumps({"answer": "它指大号盒", "evidence_ids": []}),
                                   usage_metadata={})

    monkeypatch.setattr("app.services.reports.build_model", lambda *args: Model())
    settings.model_api_key, settings.chat_model = SecretStr("test"), "test"
    second = ask_report(factory, settings, identity, "它指什么", "model",
                        first["conversation_id"], "turn2")
    assert seen["recent_history"][0]["question"] == "大号的问题是什么"
    assert ask_report(factory, settings, identity, "它指什么", "model",
                      first["conversation_id"], "turn2") == second
    other = published(env)
    with pytest.raises(ValueError, match="不属于"):
        ask_report(factory, settings, other, "问题", conversation_id=first["conversation_id"])
    assert load_report(factory, identity) == original


def test_conversation_bounded_and_busy(env):
    factory, settings = env
    identity = published(env)
    conversation = None
    for index in range(8):
        response = ask_report(factory, settings, identity, f"大号{index}",
                              conversation_id=conversation)
        conversation = response["conversation_id"]
    with factory() as session:
        assert len(session.get(ReportConversation, conversation).history) == 6
    source = load_report(factory, identity)
    start_turn(factory, identity, source["report_hash"], conversation, "busy", {"question": "x"})
    with pytest.raises(TaskConflict):
        ask_report(factory, settings, identity, "下一轮", conversation_id=conversation)


def test_native_skill_discovery_read_and_frozen_backend(env, monkeypatch):
    factory, settings = env
    settings.model_api_key, settings.chat_model = SecretStr("test"), "test"
    store = AnalysisStore(factory, settings)
    identity = store.create(AnalysisRequest(product_id="p", mode="agent"))
    path = "/skills/reviews/review-analysis/SKILL.md"
    files = store.get(identity)["versions"]["skills"]["files"]
    backend = FrozenSkillBackend(files)
    assert "评论分析" in backend.read(path).file_data["content"]
    assert backend.read("/.env").error
    with pytest.raises(PermissionError):
        backend.write(path, "overwrite")

    class Model(FakeMessagesListChatModel):
        """仅替代供应商响应，保留真实 Deep Agents 与 SkillsMiddleware。"""
        def bind_tools(self, tools, **kwargs):
            return self

    model = Model(responses=[AIMessage(content="", tool_calls=[
        {"name": "read_file", "args": {"file_path": path}, "id": "skill-read"}]),
        AIMessage(content=json.dumps({"summary": "测试", "claims": [],
                                      "missing_data": [], "next_steps": []}))])
    monkeypatch.setattr("app.agents.product_researcher.build_model", lambda *args: model)
    saver = InMemorySaver()
    run_research(settings, AnalysisRequest(product_id="p", mode="agent"),
                 store.get(identity)["snapshot"], [], RunBudget(store, identity), saver)
    checkpoint = saver.get({"configurable": {"thread_id": identity + ":research"}})
    assert checkpoint["channel_values"]["skills_metadata"]
    with factory() as session:
        calls = session.scalars(select(AnalysisCall).where(AnalysisCall.name == "read_file")).all()
        assert len(calls) == 1 and calls[0].status == "ok"
    assert freeze_skills()["hash"] == store.get(identity)["versions"]["skills"]["hash"]


def test_real_http_mcp_six_tools_and_cancel(env, monkeypatch):
    """真实 HTTP/JSON-RPC；仅向量召回替换为快照结果，取消仍由真实数据库判断。"""
    import socket
    import threading
    import time

    import uvicorn

    from app.mcp.client import research_tools
    from app.mcp.server import create_server

    factory, settings = env
    settings.evidence_transport = "mcp"
    monkeypatch.setattr("app.services.evidence_tools.search_evidence", lambda *a, **kw: [
        row for row in kw["snapshot"]["evidence"] if row["kind"] == kw["kind"]])
    tasks = TaskService(factory, settings)
    identity = tasks.create(AnalysisRequest(product_id="p", mode="agent"), "http")
    epoch = tasks.claim(identity)
    store = AnalysisStore(factory, settings)
    store.guard = lambda session: tasks.guard(session, identity, epoch)
    store.status(identity, "running")
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    settings.mcp_port = sock.getsockname()[1]
    settings.mcp_url = f"http://127.0.0.1:{settings.mcp_port}/mcp"
    server = uvicorn.Server(uvicorn.Config(create_server(settings, factory).streamable_http_app(),
                                            log_level="error"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started and time.monotonic() < deadline:
            time.sleep(.02)
        assert server.started
        with research_tools(store, identity) as tools:
            # LangGraph 会检查工具函数注解，普通函数桥接须能编译并实际调用。
            from langchain.agents import create_agent

            class Model(FakeMessagesListChatModel):
                """模拟一次自主工具调用，协议与 Agent 执行均使用真实组件。"""
                def bind_tools(self, tools, **kwargs):
                    return self

            model = Model(responses=[AIMessage(content="", tool_calls=[{
                "name": "get_product_snapshot", "args": {}, "id": "mcp-read"}]),
                AIMessage(content="已取得商品")])
            answer = create_agent(model, tools=tools).invoke({
                "messages": [{"role": "user", "content": "读取商品"}]})
            assert answer["messages"][-1].content == "已取得商品"
            by_name = {item.name: item for item in tools}
            assert len(by_name) == 6
            assert by_name["get_product_snapshot"].invoke({})["data"]["id"] == "p"
            assert by_name["query_reviews"].invoke({})["total"] == 1
            assert by_name["summarize_review_counts"].invoke({})["total"] == 1
            assert by_name["search_reviews"].invoke({"query": "渗漏"})["data"]
            assert by_name["search_rules"].invoke({"query": "规则"})["status"] == "no_results"
            assert by_name["get_evidence"].invoke({"evidence_ids": ["ev-review-r"]})["data"]
            with pytest.raises(RuntimeError, match="MCP"):
                by_name["get_evidence"].invoke({"evidence_ids": ["other"]})
            tasks.cancel(identity)
            with pytest.raises(RuntimeError, match="MCP"):
                by_name["query_reviews"].invoke({})
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        sock.close()


def test_memory_proposal_only_saved_as_candidate(env, monkeypatch):
    """模型提出建议也不能改写有效偏好，用户未允许时不保存候选。"""
    from app.db.interaction_models import MemoryCandidate

    factory, settings = env
    identity = published(env)
    settings.model_api_key, settings.chat_model = SecretStr("test"), "test"

    class Model:
        """用固定建议验证应用边界，而非测试模型是否会听从提示词。"""
        def bind(self, **kwargs):
            return self

        def invoke(self, messages):
            return SimpleNamespace(content=json.dumps({"answer": "建议待确认", "evidence_ids": [],
                    "memory_proposal": {"target_market": "US"}}), usage_metadata={})

    monkeypatch.setattr("app.services.reports.build_model", lambda *args: Model())
    answer = ask_report(factory, settings, identity, "以后关注美国", "model", suggest_memory=True)
    assert answer["memory_candidate_id"]
    ask_report(factory, settings, identity, "以后关注美国", "model", suggest_memory=False)
    with factory() as session:
        assert len(session.scalars(select(MemoryCandidate)).all()) == 1
        assert preference_snapshot(session)["version"] == 0
