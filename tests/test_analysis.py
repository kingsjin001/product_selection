"""第二期数值、证据边界、快照工具和检查点重放测试。"""

import json
from pathlib import Path

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.analysis_contracts import AnalysisRequest, Claim, CostInput, ResearchResult
from app.core.config import Settings
from app.db.analysis_models import AnalysisCall, AnalysisReport, AnalysisRun
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
            "payload": {"rating": 2, "variant": "large"},
        }],
    }


@pytest.fixture
def store(request_data, snapshot):
    """只在内存 SQLite 创建第二期表，不接触用户 PostgreSQL 数据。"""
    engine = create_engine("sqlite://")
    for table in (AnalysisRun.__table__, AnalysisReport.__table__, AnalysisCall.__table__):
        table.create(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory.begin() as session:
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
    assert tools["get_evidence"].invoke({"evidence_ids": ["bad"]})["data"] == []
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
