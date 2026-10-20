"""合成样例数据的完整性测试。"""

import csv
import json
from pathlib import Path


def _contains_chinese(value: str) -> bool:
    """判断样例展示文本是否至少包含一个中文字符。"""
    return any("\u4e00" <= char <= "\u9fff" for char in value)


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


def test_sample_data_has_twenty_chinese_records_per_type() -> None:
    """商品、评论和规则三类样例均至少 20 条，并包含中文展示文本。"""
    root = Path(__file__).resolve().parents[1] / "data" / "sample"
    with (root / "products.csv").open(encoding="utf-8-sig", newline="") as file:
        products = list(csv.DictReader(file))
    with (root / "reviews.csv").open(encoding="utf-8-sig", newline="") as file:
        reviews = list(csv.DictReader(file))
    rules = [
        json.loads(line)
        for line in (root / "rules.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert len(products) >= 20
    assert len(reviews) >= 20
    assert len(rules) >= 20
    assert all(_contains_chinese(product["product_name"]) for product in products)
    assert all(_contains_chinese(review["content"]) for review in reviews)
    assert all(_contains_chinese(rule["text"]) for rule in rules)


def test_sample_reviews_reference_existing_products() -> None:
    """每条评论都必须关联本批样例中的商品，避免导入孤立证据。"""
    root = Path(__file__).resolve().parents[1] / "data" / "sample"
    with (root / "products.csv").open(encoding="utf-8-sig", newline="") as file:
        product_ids = {row["product_id"] for row in csv.DictReader(file)}
    with (root / "reviews.csv").open(encoding="utf-8-sig", newline="") as file:
        reviews = list(csv.DictReader(file))

    assert {review["product_id"] for review in reviews} <= product_ids


def test_sample_rule_has_traceability_fields() -> None:
    """规则样例必须包含来源和版本等追溯字段。"""
    root = Path(__file__).resolve().parents[1] / "data" / "sample"
    rule = json.loads((root / "rules.jsonl").read_text(encoding="utf-8").splitlines()[0])

    assert {"rule_id", "market", "version", "source_url", "observed_at", "text"} <= rule.keys()


def test_product_specifications_are_valid_csv_embedded_json() -> None:
    """商品规格字段必须能由 CSV 和 JSON 依次正确解析。"""
    root = Path(__file__).resolve().parents[1] / "data" / "sample"
    with (root / "products.csv").open(encoding="utf-8-sig", newline="") as file:
        products = list(csv.DictReader(file))

    assert products
    assert all(None not in product for product in products)
    assert all(json.loads(product["specifications"]) for product in products)
