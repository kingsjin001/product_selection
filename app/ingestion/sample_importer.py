"""导入项目内置合成数据，并将每条数据转为可追溯 Evidence。"""

import csv
import hashlib
import json
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Evidence, ImportBatch, Product


def _sha256(value: bytes | str) -> str:
    """计算文本或字节的 SHA-256，用于内容去重和版本定位。"""
    if isinstance(value, str):
        value = value.encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def _read_jsonl(path: Path) -> list[dict]:
    """读取 JSONL 文件，忽略末尾的空白行。"""
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def _manifest_hash(data_dir: Path) -> str:
    """计算三个样例文件的组合摘要，作为幂等导入批次标识。"""
    digest = hashlib.sha256()
    for filename in ("products.csv", "reviews.csv", "rules.jsonl"):
        digest.update(filename.encode("utf-8"))
        digest.update((data_dir / filename).read_bytes())
    return digest.hexdigest()


def _parse_datetime(value: str | None) -> datetime | None:
    """将 ISO 8601 时间转换为带时区的 datetime；空值保持为空。"""
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def import_sample_data(session: Session, data_dir: Path) -> dict:
    """导入可复现的第一期样例；相同样例再次导入不会产生重复批次。"""
    manifest = _manifest_hash(data_dir)
    existing = session.scalar(select(ImportBatch).where(ImportBatch.manifest_hash == manifest))
    if existing:
        return {"batch_id": existing.id, "status": "already_imported", **existing.summary}

    products = list(csv.DictReader((data_dir / "products.csv").open(encoding="utf-8-sig")))
    reviews = list(csv.DictReader((data_dir / "reviews.csv").open(encoding="utf-8-sig")))
    rules = _read_jsonl(data_dir / "rules.jsonl")
    batch = ImportBatch(
        manifest_hash=manifest,
        source_name="phase-1-sample-data",
        summary={"products": len(products), "reviews": len(reviews), "rules": len(rules)},
    )
    session.add(batch)
    session.flush()

    for row in products:
        # merge 让商品主键固定时的重复导入保持幂等。
        session.merge(
            Product(
                id=row["product_id"],
                name=row["product_name"],
                market=row["market"],
                category=row["category"],
                specifications=json.loads(row["specifications"]),
                source_url=row.get("source_url") or None,
            )
        )

    session.flush()
    for row in reviews:
        # 评论原文、规格和来源标签共同成为证据的不可变载荷。
        payload = {
            "rating": int(row["rating"]),
            "variant": row["variant"],
            "data_kind": row["data_kind"],
            "row_id": row["review_id"],
        }
        text = row["content"].strip()
        session.add(
            Evidence(
                id=f"ev-review-{row['review_id']}",
                product_id=row["product_id"],
                import_batch_id=batch.id,
                evidence_kind="review",
                source_type="sample_csv",
                source_record_id=row["review_id"],
                source_url=row.get("source_url") or None,
                market=row["market"],
                category=row["category"],
                observed_at=_parse_datetime(row["observed_at"]),
                content_hash=_sha256(
                    json.dumps({"text": text, "payload": payload}, sort_keys=True)
                ),
                content_version="sample-v1",
                text=text,
                payload=payload,
            )
        )

    for row in rules:
        # 规则片段保留版本和适用市场，供后续 Milvus 过滤与报告引用。
        payload = {
            "title": row["title"],
            "data_kind": row["data_kind"],
            "valid_from": row["valid_from"],
            "source_file": "rules.jsonl",
        }
        text = row["text"].strip()
        session.add(
            Evidence(
                id=f"ev-rule-{row['rule_id']}",
                product_id=None,
                import_batch_id=batch.id,
                evidence_kind="rule",
                source_type="sample_jsonl",
                source_record_id=row["rule_id"],
                source_url=row.get("source_url") or None,
                market=row["market"],
                category=row["category"],
                observed_at=_parse_datetime(row["observed_at"]),
                content_hash=_sha256(
                    json.dumps({"text": text, "payload": payload}, sort_keys=True)
                ),
                content_version=row["version"],
                text=text,
                payload=payload,
            )
        )

    session.commit()
    return {"batch_id": batch.id, "status": "imported", **batch.summary}
