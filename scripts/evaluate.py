"""固定数据上的检索实验与真实 A/B/C 对照，逐条保存失败与原始输出。"""

import argparse
import hashlib
import json
import math
import statistics
import sys
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.analysis_contracts import AnalysisRequest  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.db.analysis_models import AnalysisCall  # noqa: E402
from app.db.models import Evidence  # noqa: E402
from app.db.session import get_session_factory  # noqa: E402
from app.services.analysis_store import AnalysisStore, digest  # noqa: E402
from app.services.hybrid_search import reciprocal_rank_fusion, search_evidence  # noqa: E402
from app.workflows.analysis import execute_analysis, postgres_checkpointer  # noqa: E402


def score(ranking, relevant, k=5):
    """二值相关性 Recall/nDCG，重复 ID 不增加命中数。"""
    ranking = list(dict.fromkeys(ranking))[:k]
    recall = len(set(ranking) & set(relevant)) / len(relevant)
    dcg = sum(1 / math.log2(i + 2) for i, identity in enumerate(ranking) if identity in relevant)
    ideal = sum(1 / math.log2(i + 2) for i in range(min(len(relevant), k)))
    return {"recall_at_5": recall, "ndcg_at_5": dcg / ideal if ideal else 0}


def check_frozen(factory, frozen):
    """先核对文件及数据库内容，不在变动语料上沿用旧评测标签。"""
    expected = frozen["manifest_hash"]
    assert digest({k: v for k, v in frozen.items() if k != "manifest_hash"}) == expected
    for path, file_hash in frozen["files"].items():
        assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == file_hash, path
    with factory() as session:
        current = {row.id: row.content_hash for row in session.scalars(select(Evidence))}
    assert current == frozen["corpus"], "数据库语料发生变化，不能冒用已冻结评测版本"


def save(path, value):
    """每条完成后落盘，即使后续失败也保留已经消耗的调用记录。"""
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def retrieval(factory, settings, frozen, output):
    """每条查询只生成一次向量，复用排名比较 RRF 参数，避免重复付费。"""
    queries = json.loads(Path("evals/queries.json").read_text(encoding="utf-8"))["queries"]
    result = {"date": datetime.now(UTC).isoformat(), "manifest_hash": frozen["manifest_hash"],
              "indexes": frozen["indexes"], "queries": [], "summary": {}}
    for query in queries:
        diagnostic, started = {}, monotonic()
        row = {"id": query["id"], "split": query["split"], "query": query["query"],
               "relevant": query["relevant"]}
        try:
            search_evidence(factory, settings, query=query["query"], market=query["market"],
                            kind=query["kind"], top_k=20, diagnostics=diagnostic)
            row["rankings"] = {key: value[:5] for key, value in diagnostic.items()}
            for k in (20, 100):
                row["rankings"][f"rrf_{k}"] = reciprocal_rank_fusion(
                    diagnostic["dense"], diagnostic["lexical"], k=k,
                )[:5]
            row["metrics"] = {key: score(value, query["relevant"])
                              for key, value in row["rankings"].items()}
            row["passed"] = True
        except Exception as error:
            row.update(passed=False, error=type(error).__name__)
        row["seconds"] = round(monotonic() - started, 3)
        result["queries"].append(row)
        save(output, result)
        print(f"retrieval {query['id']} passed={row['passed']}", flush=True)
    for split in ("dev", "holdout"):
        rows = [row for row in result["queries"] if row["split"] == split]
        result["summary"][split] = {}
        for method in ("lexical", "dense", "rrf", "rrf_20", "rrf_100"):
            # 服务失败记作 0，不能仅报告成功子集。
            result["summary"][split][method] = {
                metric: round(sum(r.get("metrics", {}).get(method, {}).get(metric, 0)
                                  for r in rows) / len(rows), 4)
                for metric in ("recall_at_5", "ndcg_at_5")
            }
            result["summary"][split][method]["queries"] = len(rows)
    save(output, result)


def comparison(factory, settings, frozen, output, product_ids, modes):
    """统一模型、快照与预算；少量留出样本只作工程对照，不推断总体收益。"""
    store = AnalysisStore(factory, settings)
    template = json.loads(Path("data/sample/analysis-request.json").read_text(encoding="utf-8"))
    cases = {row["product_id"]: row for row in frozen["cases"]}
    pricing = json.loads(Path("evals/pricing.example.json").read_text(encoding="utf-8"))
    result = {"date": datetime.now(UTC).isoformat(), "manifest_hash": frozen["manifest_hash"],
              "scope": "预先选择三个留出案例；每方案一次，未运行其余五个留出案例的生成对照",
              "pricing": pricing, "cases": [], "summary": {}}
    # 无模型回归覆盖全部八个留出商品；真实生成仅选择 13、17、20。
    with postgres_checkpointer(settings) as saver:
        for product_id in product_ids:
            for label, mode in (("A", "prompt"), ("B", "workflow"), ("C", "multi")):
                if label not in modes:
                    continue
                assert cases[product_id]["split"] == "holdout"
                payload = {**template, "product_id": product_id, "mode": mode,
                           "question": "核验评论中的使用限制和目标市场规则，区分已知与缺失，"
                           "给出有证据的选品条件。摘要150字内，最多3条声明，合成资料不能作真实法规。"}
                if product_id.endswith("020"):
                    payload["costs"] = None
                identity = store.create(AnalysisRequest.model_validate(payload))
                assert store.get(identity)["snapshot"] == cases[product_id]["snapshot"]
                started = monotonic()
                row = {"case": product_id, "method": label, "mode": mode, "run_id": identity,
                       "versions": store.get(identity)["versions"]}
                print(f"{label} {product_id} run_id={identity}", flush=True)
                try:
                    report = execute_analysis(store, identity, saver)
                    available = {item["id"] for item in report["evidence"]}
                    citations = [eid for claim in report["research"]["claims"]
                                 for eid in claim["evidence_ids"]]
                    numeric_ok = (not report["economics"]["scenarios"]
                                  if payload["costs"] is None else
                                  [s["contribution"] for s in report["economics"]["scenarios"]] ==
                                  ["5.15", "7.25", "9.35"])
                    row.update(passed=True, report=report, numeric_ok=numeric_ok,
                               citations={"valid": sum(eid in available for eid in citations),
                                          "total": len(citations)},
                               missing_ok=(report["economics"]["status"] == "missing_data")
                               if payload["costs"] is None else None)
                except Exception as error:
                    row.update(passed=False, error=type(error).__name__)
                row["usage"] = store.get(identity)["usage"]
                row["seconds"] = round(monotonic() - started, 3)
                row["estimated_chat_cost"] = None
                if all(pricing[k] is not None for k in ("input_per_million", "output_per_million")):
                    row["estimated_chat_cost"] = (
                        row["usage"]["input_tokens"] * pricing["input_per_million"] +
                        row["usage"]["output_tokens"] * pricing["output_per_million"]
                    ) / 1_000_000
                with factory() as session:
                    row["calls"] = [
                        {"kind": c.kind, "name": c.name, "status": c.status,
                         "latency_ms": c.latency_ms, "details": c.details}
                        for c in session.scalars(select(AnalysisCall).where(
                            AnalysisCall.run_id == identity,
                        ))
                    ]
                result["cases"].append(row)
                save(output, result)
    for label in modes:
        rows = [r for r in result["cases"] if r["method"] == label]
        result["summary"][label] = {
            "completed": sum(r["passed"] for r in rows), "total": len(rows),
            "median_seconds": statistics.median(r["seconds"] for r in rows),
            "max_seconds": max(r["seconds"] for r in rows),
            "model_calls": sum(r["usage"]["model_calls"] for r in rows),
            "tool_calls": sum(r["usage"]["tool_calls"] for r in rows),
            "input_tokens": sum(r["usage"]["input_tokens"] for r in rows),
            "output_tokens": sum(r["usage"]["output_tokens"] for r in rows),
            "numeric_ok": sum(r.get("numeric_ok", False) for r in rows),
            "citations_valid": sum(r.get("citations", {}).get("valid", 0) for r in rows),
            "citations_total": sum(r.get("citations", {}).get("total", 0) for r in rows),
        }
    save(output, result)


def main():
    """显式选择 retrieval/compare，避免不知情地发起大量真实调用。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["retrieval", "compare"])
    parser.add_argument("--output")
    parser.add_argument("--products", nargs="+",
                        default=["prod-cn-013", "prod-cn-017", "prod-cn-020"])
    parser.add_argument("--modes", nargs="+", choices=["A", "B", "C"], default=["A", "B", "C"])
    args = parser.parse_args()
    factory, settings = get_session_factory(), get_settings()
    frozen = json.loads(Path("evals/frozen-v1.json").read_text(encoding="utf-8"))
    check_frozen(factory, frozen)
    output = args.output or f"evals/{args.command}-results.json"
    if Path(output).exists():
        raise SystemExit("结果文件已存在，请用 --output 指定新实验文件，保留失败历史")
    if args.command == "retrieval":
        retrieval(factory, settings, frozen, output)
    else:
        comparison(factory, settings, frozen, output, args.products, args.modes)


if __name__ == "__main__":
    main()
