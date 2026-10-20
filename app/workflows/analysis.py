"""LangGraph 单品分析：研究、计算、引用校验、报告提交与 PostgreSQL 检查点。"""

from contextlib import contextmanager
from time import monotonic
from typing import TypedDict

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from sqlalchemy import text
from sqlalchemy.engine import make_url

from app.agents.product_researcher import run_research
from app.analysis_contracts import AnalysisRequest, Claim, ResearchResult
from app.db.task_models import Task
from app.mcp.client import research_tools
from app.services.analysis_store import AnalysisStore, RunBudget
from app.services.economics import calculate_economics
from app.services.reviews import get_review, mark_waiting, prepare_review, review_reasons
from app.tools.analysis_tools import review_counts
from app.tools.research_notes import build_note_tools


class AnalysisState(TypedDict, total=False):
    """检查点保存可序列化中间产物，重启后无需重新计算已完成节点。"""

    run_id: str
    research: dict
    economics: dict
    report: dict


def validate_references(research: ResearchResult, snapshot: dict) -> None:
    """拒绝快照之外的引用；引用可解析不等于语义支持，仍需人工评价。"""
    available = {row["id"] for row in snapshot["evidence"]}
    for claim in research.claims:
        if not set(claim.evidence_ids) <= available:
            raise ValueError("报告引用了当前快照之外的证据")


def fixed_research(snapshot: dict) -> ResearchResult:
    """B 基线：直接展示评论原文和覆盖范围，不把规则模板当作真实市场结论。"""
    rows = [row for row in snapshot["evidence"] if row["kind"] == "review"]
    return ResearchResult(
        summary=f"已读取 {len(rows)} 条当前商品评论；应结合规则、成本和真实市场数据复核。",
        claims=[
            Claim(statement=row["text"], evidence_ids=[row["id"]],
                  limitations=["原文摘录，仅代表本条样本。"])
            for row in rows[:10]
        ],
        missing_data=["未提供销量序列和竞品价格，不能判断市场增长或竞争力。"],
        next_steps=["核实资料来源及商品宣传依据，再决定是否进入候选清单。"],
    )


def report_markdown(report: dict) -> str:
    """从已验证 JSON 渲染 Markdown，不二次调用模型生成数值或引用。"""
    lines = [
        f"# {report['product']['name']} · 单品研究",
        "", f"运行：{report['run_id']}", f"模式：{report['mode']}",
        f"数据快照：{report['snapshot_hash']}", "",
        "## 研究摘要", "", report["research"]["summary"], "", "## 证据声明", "",
    ]
    for claim in report["research"]["claims"]:
        lines.extend([
            f"- {claim['statement']}", f"  引用：{', '.join(claim['evidence_ids'])}",
            f"  限制：{'；'.join(claim['limitations'])}",
        ])
    lines.extend(["", "## 单件贡献利润", ""])
    economics = report["economics"]
    if economics["status"] == "ok":
        lines.extend(["| 情景 | 收入 | 成本 | 贡献利润 |", "| --- | --- | --- | --- |"])
        for item in economics["scenarios"]:
            lines.append(
                f"| {item['name']} | {item['revenue']} | {item['cost']} | "
                f"{item['contribution']} {economics['currency']} |"
            )
    else:
        lines.append("成本不完整，未计算利润。缺失：" + "、".join(economics["missing"]))
    lines.extend(["", "## 缺失与下一步", ""])
    for item in report["research"]["missing_data"] + report["research"]["next_steps"]:
        lines.append(f"- {item}")
    lines.extend(["", "## 证据来源", ""])
    for row in report["evidence"]:
        lines.append(f"- {row['id']} | {row['version']} | {row['source_url']}")
    return "\n".join(lines) + "\n"


def build_workflow(store: AnalysisStore, run_id: str, saver, researcher=None, run_budget=None):
    """组装固定节点；研究函数可注入，以便故障测试覆盖恢复而无需真实模型。"""
    run = store.get(run_id)
    request = AnalysisRequest.model_validate(run["request"])
    snapshot = run["snapshot"]
    budget = run_budget or RunBudget(store, run_id)

    def research_node(state: AnalysisState) -> dict:
        """执行研究并立即检查引用，非法结果不会进入成本或提交阶段。"""
        budget.check()
        store.stage("research")
        if researcher:
            result = researcher(request, snapshot, budget)
        elif request.mode == "fixed":
            result = fixed_research(snapshot)
        elif request.mode == "prompt":
            result = run_research(store.settings, request, snapshot, [], budget, saver)
        else:
            # 本地和 MCP 使用同一套业务契约；上下文管理器持有完整连接生命周期。
            with research_tools(store, run_id) as tools:
                if request.mode == "workflow":
                    selected = {}
                    by_name = {item.name: item for item in tools}
                    for kind in ("review", "rule"):
                        name = "search_reviews" if kind == "review" else "search_rules"
                        with budget.call("tool", name) as details:
                            rows = by_name[name].invoke({"query": request.question})["data"]
                            details["evidence_ids"] = [row["id"] for row in rows]
                            selected.update({row["id"]: row for row in rows})
                    result = run_research(store.settings, request,
                        {**snapshot, "evidence": list(selected.values())}, [], budget, saver)
                else:
                    if request.mode == "multi":
                        tools += build_note_tools(store.factory, run_id, snapshot, store.guard)
                    result = run_research(store.settings, request, snapshot, tools, budget, saver)
        validate_references(result, snapshot)
        return {"research": result.model_dump(mode="json")}

    def calculate_node(state: AnalysisState) -> dict:
        """成本计算只依赖用户参数，模型不能修改该节点输出。"""
        budget.check()
        store.stage("calculate")
        return {"economics": calculate_economics(request.costs)}

    def validate_node(state: AnalysisState) -> dict:
        """最后一次校验结构和引用，并将原始证据随报告冻结保存。"""
        budget.check()
        store.stage("validate")
        result = ResearchResult.model_validate(state["research"])
        validate_references(result, snapshot)
        return {"report": {
            "schema_version": "report-v2", "run_id": run_id, "mode": request.mode,
            "snapshot_hash": snapshot["hash"], "product": snapshot["product"],
            "research": result.model_dump(mode="json"),
            "review_statistics": review_counts(snapshot),
            "economics": state["economics"], "evidence": snapshot["evidence"],
            "versions": run["versions"], "usage": store.get(run_id)["usage"],
        }}

    def review_node(state: AnalysisState) -> dict:
        """原生动态中断只返回待审草稿，恢复时验证持久决定与草稿摘要。"""
        reasons = review_reasons(request, state["report"])
        if not reasons:
            return {}
        budget.check()
        store.stage("review")
        pending = prepare_review(store, run_id, state["report"], reasons)
        decision = interrupt(pending)
        stored = get_review(store.factory, run_id)
        if (stored["status"] != "approve" or decision != stored["decision"]
                or stored["draft_hash"] != pending["draft_hash"]):
            raise ValueError("人工决定与当前草稿不匹配")
        return {}

    def persist_node(state: AnalysisState) -> dict:
        """报告与终态原子提交，检查点重放时仍只保留一份报告。"""
        budget.check()
        store.stage("persist")
        store.save_report(run_id, state["report"], report_markdown(state["report"]))
        return {}

    graph = StateGraph(AnalysisState)
    for name, node in (
        ("research", research_node), ("calculate", calculate_node),
        ("validate", validate_node), ("review", review_node), ("persist", persist_node),
    ):
        graph.add_node(name, node)
    graph.add_edge(START, "research")
    graph.add_edge("research", "calculate")
    graph.add_edge("calculate", "validate")
    graph.add_edge("validate", "review")
    graph.add_edge("review", "persist")
    graph.add_edge("persist", END)
    return graph.compile(checkpointer=saver)


@contextmanager
def postgres_checkpointer(settings):
    """使用官方 PostgreSQL 检查点，启动时确保其表结构存在。"""
    url = make_url(settings.database_url).set(drivername="postgresql")
    with PostgresSaver.from_conn_string(url.render_as_string(hide_password=False)) as saver:
        saver.setup()
        yield saver


def execute_analysis(store: AnalysisStore, run_id: str, saver, researcher=None) -> dict:
    """同一运行串行执行；失败可基于已完成节点检查点恢复。"""
    existing = store.report(run_id)
    if existing:
        return existing
    if store.guard is None:
        with store.factory() as session:
            if session.get(Task, run_id):
                raise ValueError("后台任务只能通过 Worker 执行，请使用任务恢复接口")
    run = store.get(run_id)
    if run["status"] == "cancelled":
        raise ValueError("已取消运行不能继续")
    frozen = run["versions"]
    if run["request"]["mode"] != "fixed" and (
        frozen["model"] != store.settings.chat_model
        or frozen["embedding"] != store.settings.embedding_model
        or frozen["embedding_dim"] != store.settings.embedding_dim
        or frozen["embedding_provider"] != store.settings.embedding_provider
        or frozen.get("milvus_database", "default") != store.settings.milvus_database
    ):
        raise ValueError("恢复时模型配置与原运行不一致；请恢复原配置或创建新运行")
    # 连接级 advisory lock 随进程/连接退出释放，防止多个请求同时恢复同一图。
    with store.factory() as lock_session, lock_session.get_bind().connect() as lock_connection:
        locked = lock_connection.execute(
            text("SELECT pg_try_advisory_lock(hashtextextended(:run_id, 0))"), {"run_id": run_id},
        ).scalar()
        if not locked:
            raise RuntimeError("该运行正在执行，请勿并发恢复")
        try:
            existing = store.report(run_id)
            if existing:
                return existing
            store.status(run_id, "running")
            budget = RunBudget(store, run_id)
            graph = build_workflow(store, run_id, saver, researcher, run_budget=budget)
            config = {"configurable": {"thread_id": run_id}}
            saved = graph.get_state(config)
            value = None if saved.values else {"run_id": run_id}
            if saved.interrupts:
                review = get_review(store.factory, run_id)
                if review["status"] == "approve":
                    value = Command(resume=review["decision"])
            result = graph.invoke(value, config)
            if result.get("__interrupt__"):
                mark_waiting(store, run_id, budget.deadline - monotonic())
                return {"run_id": run_id, "status": "waiting_for_review"}
            return store.report(run_id)
        except Exception as error:
            store.status(run_id, "failed", type(error).__name__)
            raise
        finally:
            lock_connection.execute(
                text("SELECT pg_advisory_unlock(hashtextextended(:run_id, 0))"), {"run_id": run_id},
            )
