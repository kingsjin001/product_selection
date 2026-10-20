"""第三期真实服务验收，记录三类问题的调用轨迹，不隐藏失败结果。"""

import argparse
import json
import sys
from pathlib import Path
from time import monotonic

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.analysis_contracts import AnalysisRequest  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.db.analysis_models import AnalysisCall  # noqa: E402
from app.db.session import get_session_factory  # noqa: E402
from app.services.analysis_store import AnalysisStore  # noqa: E402
from app.services.hybrid_search import search_evidence  # noqa: E402
from app.services.indexing import enqueue_all, sync_events  # noqa: E402
from app.workflows.analysis import execute_analysis, postgres_checkpointer  # noqa: E402


def main():
    """使用现有合成样例调用真实模型；输出可定位 run_id 和工具名。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-index", action="store_true")
    parser.add_argument("--output", default="docs/acceptance/phase-3-results.json")
    args = parser.parse_args()
    settings, factory = get_settings(), get_session_factory()
    store = AnalysisStore(factory, settings)
    output = Path(args.output)
    result = {"index": {}, "retrieval": [], "cases": []}
    if not args.skip_index:
        count = enqueue_all(factory)
        result["index"] = {"enqueued": count, **sync_events(factory, settings, limit=count + 100)}
        assert result["index"]["failed"] == 0, result["index"]
    for kind, query in [("rule", "宣传依据与商品描述"), ("review", "大号漏水")]:
        hits = search_evidence(factory, settings, query=query, market="US", kind=kind)
        result["retrieval"].append({"kind": kind, "query": query,
                                    "evidence_ids": [row["id"] for row in hits]})
        assert hits
    template = json.loads(Path("data/sample/analysis-request.json").read_text(encoding="utf-8"))
    questions = [
        ("normal", "分别委派 reviews 和 rules 两个专项助手研究，再综合选品条件。"),
        ("missing", "查询这个商品过去90天销量与竞争对手价格；证据没有就明确缺失并停止。"),
        ("conflict", "请委派 reviews 查大号与小号密封评论有无冲突，按规格补查；"
                     "委派 rules 核验防漏宣传，保存研究笔记后给出条件结论。"),
    ]
    with postgres_checkpointer(settings) as saver:
        for name, question in questions:
            data = {**template, "mode": "multi", "question": question}
            run_id = store.create(AnalysisRequest.model_validate(data))
            print(f"{name} run_id={run_id}", flush=True)
            started = monotonic()
            case = {"case": name, "run_id": run_id}
            try:
                report = execute_analysis(store, run_id, saver)
                case.update(passed=True, usage=report["usage"], research=report["research"])
                assert saver.get_tuple({"configurable": {"thread_id": f"{run_id}:research"}})
            except Exception as error:
                case.update(passed=False, error=type(error).__name__)
            with factory() as session:
                calls = session.scalars(select(AnalysisCall).where(
                    AnalysisCall.run_id == run_id,
                )).all()
                case["calls"] = [{"kind": c.kind, "name": c.name, "status": c.status,
                                  "latency_ms": c.latency_ms} for c in calls]
            case["seconds"] = round(monotonic() - started, 2)
            result["cases"].append(case)
            output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"{name} passed={case['passed']}", flush=True)
    assert all(case["passed"] for case in result["cases"]), "请检查报告中的失败轨迹"


if __name__ == "__main__":
    main()
