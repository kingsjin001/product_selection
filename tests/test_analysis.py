"""第二期数值、证据边界、快照工具和检查点重放测试。"""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import SecretStr, ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.agents.product_researcher import ResearchMiddleware, run_research
from app.analysis_contracts import AnalysisRequest, Claim, CostInput, ResearchResult
from app.core.config import Settings
from app.db.analysis_models import AnalysisRun
from app.db.index_models import EvidenceState
from app.db.models import Evidence, ImportBatch, Product
from app.db.session import Base
from app.services.analysis_store import AnalysisStore, BudgetExceeded, RunBudget
from app.services.economics import calculate_economics
from app.tools.analysis_tools import build_tools, review_counts
from app.workflows.analysis import build_workflow, fixed_research, validate_references


@pytest.fixture
def request_data():
    """复用交付给用户的完整样例，避免测试与说明中的数值分离。"""
    path = Path(__file__).parents[1] / "data/sample/analysis-request.json"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def snapshot():
    """极小冻结证据集，覆盖一条已知负面评论。"""
    return {
        "hash": "test-snapshot", "product": {"id": "p", "name": "保鲜盒", "market": "US"},
        "evidence": [{
            "id": "e1", "kind": "review", "text": "大号盒盖漏水",
            "version": "v1", "source_url": "https://example.invalid/e1",
            "content_hash": "test-hash",
            "payload": {"rating": 2, "variant": "large"},
        }],
    }


@pytest.fixture
def store(request_data, snapshot):
    """只在内存 SQLite 创建第二期表，不接触用户 PostgreSQL 数据。"""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory.begin() as session:
        session.add(ImportBatch(id="batch", manifest_hash="test", source_name="test"))
        session.add(Product(id="p", name="保鲜盒", market="US", category="home"))
        session.flush()
        session.add(Evidence(
            id="e1", product_id="p", import_batch_id="batch", evidence_kind="review",
            source_type="test", source_record_id="e1", market="US", category="home",
            content_hash="test-hash", content_version="v1", text="大号盒盖漏水",
            payload={"rating": 2, "variant": "large"},
        ))
        session.add(AnalysisRun(
            id="test-run", status="pending", request=request_data, snapshot=snapshot,
            versions={"limits": {"model": 2, "tool": 3, "seconds": 60}},
        ))
    yield AnalysisStore(factory, Settings(_env_file=None))
    engine.dispose()


def test_decimal_calculation_and_scenarios(request_data):
    """验算 25 - 6 - 4 - .5 - 1.5 - 2.5 - 2 - .75 - .5 = 7.25。"""
    result = calculate_economics(CostInput.model_validate(request_data["costs"]))
    assert result["scenarios"][1]["contribution"] == "7.25"
    assert result["scenarios"][0]["contribution"] == "5.15"
    assert result["scenarios"][2]["contribution"] == "9.35"


@pytest.mark.parametrize("field", ["shipping", "platform_rate", "other"])
def test_missing_costs_never_become_zero(request_data, field):
    """任一关键成本缺失都不能输出看似完整的利润。"""
    request_data["costs"].pop(field)
    result = calculate_economics(CostInput.model_validate(request_data["costs"]))
    assert result["status"] == "missing_data"
    assert result["missing"] == [field]
    assert result["scenarios"] == []


def test_invalid_rate_rejected(request_data):
    """费率误填为百分数整数时必须明确拒绝。"""
    request_data["costs"]["platform_rate"] = "6"
    with pytest.raises(ValidationError):
        AnalysisRequest.model_validate(request_data)


def test_unknown_citation_rejected(snapshot):
    """编造证据 ID 不得通过最终校验。"""
    result = ResearchResult(summary="测试", claims=[Claim(statement="未知", evidence_ids=["bad"])])
    with pytest.raises(ValueError, match="快照之外"):
        validate_references(result, snapshot)


def test_tools_are_bound_to_snapshot(snapshot):
    """只读工具按规格和评分过滤，未知 ID 不会泄漏其他商品数据。"""
    tools = {item.name: item for item in build_tools(snapshot, lambda query, k: [])}
    assert tools["query_reviews"].invoke({"variant": "large"})["total"] == 1
    assert tools["query_reviews"].invoke({"variant": "small"})["total"] == 0
    with pytest.raises(PermissionError):
        tools["get_evidence"].invoke({"evidence_ids": ["bad"]})
    assert review_counts(snapshot)["ratings"] == {"2": 1}


def test_failed_calls_still_consume_persistent_budget(store):
    """失败请求计费预留，创建新的预算对象不能绕过之前消费。"""
    budget = RunBudget(store, "test-run")
    with pytest.raises(RuntimeError), budget.call("model", "failure"):
        raise RuntimeError("injected")
    with RunBudget(store, "test-run").call("model", "success"):
        pass
    with pytest.raises(BudgetExceeded), RunBudget(store, "test-run").call("model", "blocked"):
        pass
    assert store.get("test-run")["usage"]["model_calls"] == 2


def test_resume_after_persist_failure_skips_completed_research(store, monkeypatch):
    """提交故障后恢复已完成研究结果，报告重复提交仍保持唯一。"""
    saver = InMemorySaver()
    research_calls = []

    def researcher(request, snapshot, budget):
        """记录研究调用次数，模拟昂贵的模型研究。"""
        research_calls.append(1)
        return fixed_research(snapshot)

    original = store.save_report

    def fail(*args):
        """注入报告落库之前的崩溃。"""
        raise RuntimeError("injected failure")

    monkeypatch.setattr(store, "save_report", fail)
    config = {"configurable": {"thread_id": "test-run"}}
    graph = build_workflow(store, "test-run", saver, researcher)
    with pytest.raises(RuntimeError, match="injected"):
        graph.invoke({"run_id": "test-run"}, config)
    assert graph.get_state(config).next == ("persist",)
    monkeypatch.setattr(store, "save_report", original)
    build_workflow(store, "test-run", saver, researcher).invoke(None, config)
    report = store.report("test-run")
    original("test-run", report, "重复写入不能替换")
    assert len(research_calls) == 1
    assert report["economics"]["scenarios"][1]["contribution"] == "7.25"
    assert store.get("test-run")["status"] == "completed"


def test_deleted_evidence_cannot_be_published(store):
    """冻结快照后再删除证据，提交必须拒绝，不能发布过时引用。"""
    with store.factory.begin() as session:
        session.add(EvidenceState(evidence_id="e1", active=False))
    graph = build_workflow(store, "test-run", InMemorySaver())
    with pytest.raises(ValueError, match="已经更新或删除"):
        graph.invoke({"run_id": "test-run"}, {"configurable": {"thread_id": "test-run"}})
    assert store.report("test-run") is None


@pytest.mark.parametrize("tool_call", [
    {"name": "execute", "args": {"command": "untrusted"}},
    {"name": "task", "args": {"subagent_type": "general-purpose"}},
])
def test_untrusted_tool_and_default_subagent_blocked(store, tool_call):
    """即使模型服从评论中的注入指令，也不能执行白名单外能力。"""
    middleware = ResearchMiddleware(RunBudget(store, "test-run"), {"task", "query_reviews"})
    with pytest.raises(PermissionError):
        middleware.wrap_tool_call(SimpleNamespace(tool_call=tool_call), lambda req: None)


@pytest.mark.parametrize("repair_valid", [True, False])
def test_json_repair_has_finite_calls(store, snapshot, monkeypatch, repair_valid):
    """无效 JSON 只修复一次；第二次仍无效立即失败，不形成隐式循环。"""
    outputs = ["不是 JSON", '{"summary":"资料不足","claims":[]}' if repair_valid else "仍无效"]

    class FakeModel:
        """模拟 JSON 约束仍可能失效的供应商。"""

        def bind(self, **kwargs):
            return self

        def invoke(self, messages):
            return SimpleNamespace(content=outputs.pop(0), usage_metadata={"input_tokens": 1})

    monkeypatch.setattr("app.agents.product_researcher.build_model", lambda *args: FakeModel())
    settings = store.settings.model_copy(
        update={"model_api_key": SecretStr("unit-test"), "chat_model": "test"},
    )
    request = AnalysisRequest(product_id="p", mode="prompt")
    if repair_valid:
        assert run_research(settings, request, snapshot, [], RunBudget(store, "test-run"),
                            None).summary == "资料不足"
    else:
        with pytest.raises(ValidationError):
            run_research(settings, request, snapshot, [], RunBudget(store, "test-run"), None)
    assert store.get("test-run")["usage"]["model_calls"] == 2
    assert not outputs


@pytest.mark.parametrize("message", ["429 rate limited", "model timed out"])
def test_provider_failures_are_counted_without_hidden_retry(store, message):
    """模拟供应商限流和超时，验证异常计入预留额度并直接交给恢复流程。"""
    calls = []

    def failed_handler(request):
        calls.append(1)
        raise TimeoutError(message)

    middleware = ResearchMiddleware(RunBudget(store, "test-run"), set())
    request = SimpleNamespace(tools=[], override=lambda **kwargs: None)
    with pytest.raises(TimeoutError):
        middleware.wrap_model_call(request, failed_handler)
    assert len(calls) == 1
    assert store.get("test-run")["usage"]["model_calls"] == 1
