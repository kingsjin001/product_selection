"""合成样例数据的完整性测试。"""

import json
from pathlib import Path


def test_sample_data_declares_itself_synthetic() -> None:
    """样例说明必须明确其为合成数据。"""
    root = Path(__file__).resolve().parents[1] / "data" / "sample"
    review_rows = (root / "reviews.csv").read_text(encoding="utf-8-sig")
    rules = [
        json.loads(line)
        for line in (root / "rules.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert "synthetic" in review_rows
    assert rules
    assert all(rule["data_kind"] == "synthetic" for rule in rules)


def test_sample_rule_has_traceability_fields() -> None:
    """规则样例必须包含来源和版本等追溯字段。"""
    root = Path(__file__).resolve().parents[1] / "data" / "sample"
    rule = json.loads((root / "rules.jsonl").read_text(encoding="utf-8").splitlines()[0])

    assert {"rule_id", "market", "version", "source_url", "observed_at", "text"} <= rule.keys()
