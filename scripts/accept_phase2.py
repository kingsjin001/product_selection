"""第二期真实 PostgreSQL 验收：五个完整案例、三个缺失案例及检查点重放。"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

# 支持从项目根目录直接执行脚本，不依赖 pip editable 安装状态。
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.analysis_contracts import AnalysisRequest  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.core.logging import configure_logging  # noqa: E402
from app.db.session import get_session_factory  # noqa: E402
from app.services.analysis_store import AnalysisStore  # noqa: E402
from app.workflows.analysis import execute_analysis, postgres_checkpointer  # noqa: E402


def main():
    """默认不调用真实模型；--live 额外验证一个真实 Agent，结果单独标识。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    settings = get_settings()
    configure_logging(settings.log_level)
    store = AnalysisStore(get_session_factory(), settings)
    template = json.loads(Path("data/sample/analysis-request.json").read_text(encoding="utf-8"))
    results = []
    with postgres_checkpointer(settings) as saver:
        for index in range(8):
            data = json.loads(json.dumps(template))
            data["product_id"] = f"prod-cn-{index + 1:03}"
            if index >= 5:
                del data["costs"][("shipping", "other", "platform_rate")[index - 5]]
            run_id = store.create(AnalysisRequest.model_validate(data))
            report = execute_analysis(store, run_id, saver)
            expected = "ok" if index < 5 else "missing_data"
            assert report["economics"]["status"] == expected
            assert execute_analysis(store, run_id, saver) == report
            assert saver.get_tuple({"configurable": {"thread_id": run_id}})
            results.append({"run_id": run_id, "case": index + 1, "expected": expected,
                            "passed": True, "mode": "fixed"})
        if args.live:
            template["mode"] = "agent"
            run_id = store.create(AnalysisRequest.model_validate(template))
            print("live_run_id=" + run_id, flush=True)
            report = execute_analysis(store, run_id, saver)
            results.append({"run_id": run_id, "mode": "agent", "passed": True,
                            "usage": report["usage"]})
    artifact = {
        "date": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
        "live_model": args.live, "cases": results,
    }
    output = Path("docs/acceptance/phase-2-results.json")
    output.write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"passed": len(results), "output": str(output)}))


if __name__ == "__main__":
    main()
