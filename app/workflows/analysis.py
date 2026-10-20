"""LangGraph 单品分析：研究、计算、引用校验、报告提交与 PostgreSQL 检查点。"""

from contextlib import contextmanager
from typing import TypedDict

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END, START, StateGraph
from sqlalchemy import text
from sqlalchemy.engine import make_url

from app.agents.product_researcher import run_research
from app.analysis_contracts import AnalysisRequest, Claim, ResearchResult
from app.core.embeddings import EmbeddingService
from app.db.task_models import Task
from app.repositories.milvus import MilvusRuleRepository
from app.services.analysis_store import AnalysisStore, RunBudget
from app.services.economics import calculate_economics
from app.services.hybrid_search import search_evidence
from app.tools.analysis_tools import build_tools, review_counts
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


def build_workflow(store: AnalysisStore, run_id: str, saver, researcher=None):
    """组装固定节点；研究函数可注入，以便故障测试覆盖恢复而无需真实模型。"""
    run = store.get(run_id)
    request = AnalysisRequest.model_validate(run["request"])
    snapshot = run["snapshot"]
    budget = RunBudget(store, run_id)

    def search_frozen_rules(query: str, top_k: int) -> list[dict]:
        """Milvus 召回后仅返回快照内正文，避免运行途中发生输入漂移。"""
        embedding = EmbeddingService(store.settings).embed_one(query)
        hits = MilvusRuleRepository(store.settings).search(
            embedding, snapshot["product"]["market"], max(top_k, 10),
        )
        frozen = {row["id"]: row for row in snapshot["evidence"] if row["kind"] == "rule"}
        return [frozen[hit["evidence_id"]] for hit in hits if hit["evidence_id"] in frozen][:top_k]

    def research_node(state: AnalysisState) -> dict:
        """执行研究并立即检查引用，非法结果不会进入成本或提交阶段。"""
        budget.check()
        store.stage("research")
        if researcher:
            result = researcher(request, snapshot, budget)
        elif request.mode == "fixed":
            result = fixed_research(snapshot)
        elif request.mode == "workflow":
            # B 对照：固定查询路径，同样使用 RRF 与原快照，但不允许自主循环。
            selected = {}
            for kind in ("review", "rule"):
                with budget.call("tool", f"fixed_search_{kind}") as details:
                    rows = search_evidence(
                        store.factory, store.settings, query=request.question, kind=kind,
                        market=snapshot["product"]["market"],
                        category=snapshot["product"]["category"],
                        product_id=request.product_id if kind == "review" else "",
                        snapshot=snapshot,
                    )
                    details["evidence_ids"] = [row["id"] for row in rows]
                    selected.update({row["id"]: row for row in rows})
            result = run_research(store.settings, request,
                                  {**snapshot, "evidence": list(selected.values())},
                                  [], budget, saver)
        else:
            if request.mode == "multi":
                def retrieve(kind, query, top_k):
                    """第三期同时使用版本过滤、品类/商品过滤和 RRF。"""
                    return search_evidence(
                        store.factory, store.settings, query=query, top_k=top_k, kind=kind,
                        market=snapshot["product"]["market"],
                        category=snapshot["product"]["category"],
                        product_id=request.product_id if kind == "review" else "",
                        snapshot=snapshot,
                    )
                tools = build_tools(
                    snapshot, lambda q, k: retrieve("rule", q, k),
                    lambda q, k: retrieve("review", q, k),
                ) + build_note_tools(store.factory, run_id, snapshot, store.guard)
            else:
                tools = build_tools(snapshot, search_frozen_rules)
            result = run_research(
                store.settings, request, snapshot, tools,
                budget, saver,
            )
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

    def persist_node(state: AnalysisState) -> dict:
        """报告与终态原子提交，检查点重放时仍只保留一份报告。"""
        budget.check()
        store.stage("persist")
        store.save_report(run_id, state["report"], report_markdown(state["report"]))
        return {}

    graph = StateGraph(AnalysisState)
    for name, node in (
        ("research", research_node), ("calculate", calculate_node),
        ("validate", validate_node), ("persist", persist_node),
    ):
        graph.add_node(name, node)
    graph.add_edge(START, "research")
    graph.add_edge("research", "calculate")
    graph.add_edge("calculate", "validate")
    graph.add_edge("validate", "persist")
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
    frozen = run["versions"]
    if run["request"]["mode"] != "fixed" and (
        frozen["model"] != store.settings.chat_model
        or frozen["embedding"] != store.settings.embedding_model
        or frozen["embedding_dim"] != store.settings.embedding_dim
        or frozen["embedding_provider"] != store.settings.embedding_provider
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
            graph = build_workflow(store, run_id, saver, researcher)
            config = {"configurable": {"thread_id": run_id}}
            saved = graph.get_state(config)
            graph.invoke(None if saved.values else {"run_id": run_id}, config)
            return store.report(run_id)
        except Exception as error:
            store.status(run_id, "failed", type(error).__name__)
            raise
        finally:
            lock_connection.execute(
                text("SELECT pg_advisory_unlock(hashtextextended(:run_id, 0))"), {"run_id": run_id},
            )
