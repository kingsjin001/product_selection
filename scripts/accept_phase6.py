"""最终无模型回归：覆盖全部八个留出商品和持久事件 HTTP 补发。"""

import json
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from app.analysis_contracts import AnalysisRequest  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.db.session import get_session_factory  # noqa: E402
from app.main import app  # noqa: E402
from app.services.analysis_store import AnalysisStore  # noqa: E402
from app.services.tasks import TaskService  # noqa: E402
from app.workers.runner import run_task  # noqa: E402
from scripts.evaluate import check_frozen  # noqa: E402


def main():
    """核心一致性通过实际数据库和 FastAPI 路由验证，不依赖付费模型。"""
    factory, settings = get_session_factory(), get_settings()
    frozen = json.loads(Path("evals/frozen-v1.json").read_text(encoding="utf-8"))
    check_frozen(factory, frozen)
    template = json.loads(Path("data/sample/analysis-request.json").read_text(encoding="utf-8"))
    tasks, store, client = TaskService(factory, settings), AnalysisStore(factory, settings), \
        TestClient(app)
    results = []
    cases = [row for row in frozen["cases"] if row["split"] == "holdout"]
    for index, case in enumerate(cases):
        payload = {**template, "product_id": case["product_id"], "mode": "fixed"}
        if index >= 5:
            payload["costs"] = None
        identity = tasks.create(AnalysisRequest.model_validate(payload), "final-" + uuid4().hex)
        assert run_task(identity)["status"] == "completed"
        report = store.report(identity)
        assert store.get(identity)["snapshot"] == case["snapshot"]
        assert report["economics"]["status"] == ("missing_data" if index >= 5 else "ok")
        assert run_task(identity)["status"] == "duplicate_or_terminal"
        response = client.get(f"/api/tasks/{identity}/events", headers={"Last-Event-ID": "3"})
        assert response.status_code == 200
        frames = [part for part in response.text.split("\n\n") if part.startswith("id: ")]
        expected = tasks.events(identity, after=3)
        assert len(frames) == len(expected)
        assert len({frame.splitlines()[0] for frame in frames}) == len(frames)
        results.append({"product_id": case["product_id"], "run_id": identity,
                        "passed": True, "economics": report["economics"]["status"],
                        "replayed_events": len(frames)})
    Path("docs/acceptance/phase-6-regression.json").write_text(
        json.dumps({"cases": results, "paid_model_calls": 0}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps({"passed": len(results)}))


if __name__ == "__main__":
    main()
