"""第二期 CLI：创建、恢复单品分析并导出同源 JSON/Markdown 报告。"""

import argparse
import json
from pathlib import Path

from app.analysis_contracts import AnalysisRequest
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import get_session_factory
from app.services.analysis_store import AnalysisStore
from app.workflows.analysis import execute_analysis, postgres_checkpointer, report_markdown


def main() -> None:
    """指定请求文件创建运行，或使用 run-id 从已有检查点恢复。"""
    parser = argparse.ArgumentParser(description="单品分析：运行、恢复及报告导出")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--input", type=Path, help="AnalysisRequest JSON 文件")
    group.add_argument("--run-id", help="已有运行 ID；已完成时复用报告")
    parser.add_argument("--output", type=Path, default=Path("exports"))
    args = parser.parse_args()
    settings = get_settings()
    configure_logging(settings.log_level)
    store = AnalysisStore(get_session_factory(), settings)
    run_id = args.run_id
    if args.input:
        request = AnalysisRequest.model_validate_json(args.input.read_text(encoding="utf-8-sig"))
        run_id = store.create(request)
    print(f"run_id={run_id}", flush=True)
    with postgres_checkpointer(settings) as saver:
        report = execute_analysis(store, run_id, saver)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / f"{run_id}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    (args.output / f"{run_id}.md").write_text(report_markdown(report), encoding="utf-8")
    print(json.dumps({"run_id": run_id, "status": "completed", "output": str(args.output)}))


if __name__ == "__main__":
    main()
