"""一次性冻结开发/留出拆分、输入快照、查询集和向量空间身份。"""

import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.analysis_contracts import AnalysisRequest  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.db.models import Evidence  # noqa: E402
from app.db.session import get_session_factory  # noqa: E402
from app.repositories.vectors import vector_identity  # noqa: E402
from app.services.analysis_store import analysis_versions, digest, freeze_snapshot  # noqa: E402


def main():
    """已存在的冻结文件绝不静默重写，修改数据应另建一个评测版本。"""
    settings, factory = get_settings(), get_session_factory()
    output = Path("evals/frozen-v1.json")
    if output.exists():
        raise SystemExit("冻结文件已存在；请保留它，另建版本进行新的实验")
    result = {"version": "eval-v1", "created_at": datetime.now(UTC).isoformat(),
              "versions": analysis_versions(settings), "cases": [], "files": {},
              "indexes": {kind: vector_identity(settings, kind) for kind in ("rule", "review")}}
    with factory() as session:
        for index in range(1, 21):
            identity = f"prod-cn-{index:03}"
            snapshot = freeze_snapshot(session, AnalysisRequest(product_id=identity))
            result["cases"].append({"product_id": identity,
                                    "split": "dev" if index <= 12 else "holdout",
                                    "snapshot": snapshot})
        result["corpus"] = {row.id: row.content_hash for row in
                            session.scalars(select(Evidence).order_by(Evidence.id))}
    for path in ("data/sample/products.csv", "data/sample/reviews.csv",
                 "data/sample/rules.jsonl", "evals/queries.json"):
        result["files"][path] = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    result["manifest_hash"] = digest(result)
    with output.open("x", encoding="utf-8") as target:
        json.dump(result, target, ensure_ascii=False, indent=2)
    print(json.dumps({"frozen": str(output), "cases": 20, "dev": 12, "holdout": 8,
                      "corpus": len(result["corpus"])}))


if __name__ == "__main__":
    main()
