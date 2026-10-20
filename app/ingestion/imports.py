"""用户 JSON/CSV 导入契约与原子写入，冲突时拒绝覆盖已有证据。"""

import json
from datetime import datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select

from app.db.index_models import EvidenceState, IndexEvent
from app.db.models import Evidence, ImportBatch, Product
from app.services.analysis_store import digest


class ProductInput(BaseModel):
    """兼容第一期 products.csv 字段。"""

    model_config = ConfigDict(extra="forbid")
    product_id: str = Field(min_length=1, max_length=80)
    product_name: str = Field(min_length=1, max_length=255)
    market: str = Field(pattern=r"^[A-Z]{2,12}$")
    category: str = Field(min_length=1, max_length=120)
    specifications: dict = Field(default_factory=dict)
    source_url: str | None = Field(default=None, max_length=1024)

    @field_validator("source_url", mode="before")
    @classmethod
    def empty_source(cls, value):
        """CSV 空单元格与 JSON null 使用同一规范值。"""
        return value or None

    @field_validator("specifications", mode="before")
    @classmethod
    def parse_specifications(cls, value):
        """CSV 的规格 JSON 字符串与 JSON 对象都可读取。"""
        return json.loads(value) if isinstance(value, str) else value


class ReviewInput(BaseModel):
    """评分为 1～5，明确标记数据是合成还是用户导入。"""

    model_config = ConfigDict(extra="forbid")
    review_id: str = Field(min_length=1, max_length=60)
    product_id: str = Field(min_length=1, max_length=80)
    market: str = Field(pattern=r"^[A-Z]{2,12}$")
    category: str = Field(min_length=1, max_length=120)
    rating: int = Field(ge=1, le=5)
    variant: str = Field(min_length=1, max_length=120)
    content: str = Field(min_length=1, max_length=8000)
    observed_at: datetime
    data_kind: Literal["synthetic", "user_provided"] = "user_provided"
    source_url: str | None = Field(default=None, max_length=1024)

    @field_validator("source_url", mode="before")
    @classmethod
    def empty_source(cls, value):
        """空来源不被解释为有效网址。"""
        return value or None


class RuleInput(BaseModel):
    """规则是来源片段，不因导入成功就获得真实性或合规保证。"""

    model_config = ConfigDict(extra="forbid")
    rule_id: str = Field(min_length=1, max_length=60)
    title: str = Field(min_length=1, max_length=255)
    market: str = Field(pattern=r"^[A-Z]{2,12}$")
    category: str = Field(min_length=1, max_length=120)
    text: str = Field(min_length=1, max_length=8000)
    version: str = Field(min_length=1, max_length=64)
    valid_from: str = Field(min_length=10, max_length=10)
    observed_at: datetime
    data_kind: Literal["synthetic", "user_provided"] = "user_provided"
    source_url: str | None = Field(default=None, max_length=1024)

    @field_validator("source_url", mode="before")
    @classmethod
    def empty_source(cls, value):
        """空来源不被解释为有效网址。"""
        return value or None


class ImportRequest(BaseModel):
    """一个批次可只导入一种类型，每类最多 5000 条。"""

    model_config = ConfigDict(extra="forbid")
    products: list[ProductInput] = Field(default_factory=list, max_length=5000)
    reviews: list[ReviewInput] = Field(default_factory=list, max_length=5000)
    rules: list[RuleInput] = Field(default_factory=list, max_length=5000)


def import_records(factory, request: ImportRequest):
    """同批次复用；同 ID 异内容拒绝；全部校验及 outbox 与导入同事务。"""
    if not (request.products or request.reviews or request.rules):
        raise ValueError("导入批次不能为空")
    manifest = digest(request.model_dump(mode="json"))
    with factory.begin() as session:
        batch = session.scalar(select(ImportBatch).where(ImportBatch.manifest_hash == manifest))
        if batch:
            return {"batch_id": batch.id, "status": "already_imported", **batch.summary}
        batch = ImportBatch(id=str(uuid4()), manifest_hash=manifest, source_name="user-import",
                            summary={"products": 0, "reviews": 0, "rules": 0})
        session.add(batch)
        session.flush()
        counts = dict(batch.summary)
        seen = set()
        for item in request.products:
            if item.product_id in seen:
                raise ValueError(f"商品编号重复：{item.product_id}")
            seen.add(item.product_id)
            values = {"name": item.product_name, "market": item.market, "category": item.category,
                      "specifications": item.specifications, "source_url": item.source_url}
            existing = session.get(Product, item.product_id)
            if existing:
                if any(getattr(existing, key) != value for key, value in values.items()):
                    raise ValueError(f"商品已存在且内容不同，不会覆盖：{item.product_id}")
            else:
                session.add(Product(id=item.product_id, **values))
                counts["products"] += 1
        session.flush()
        seen = set()
        for kind, items in (("review", request.reviews), ("rule", request.rules)):
            for item in items:
                raw_id = item.review_id if kind == "review" else item.rule_id
                identity = f"ev-{kind}-{raw_id}"
                if identity in seen:
                    raise ValueError(f"批次内证据 ID 重复：{identity}")
                seen.add(identity)
                product_id = item.product_id if kind == "review" else None
                if product_id:
                    product = session.get(Product, product_id)
                    if (not product or product.market != item.market
                            or product.category != item.category):
                        raise ValueError(f"评论的商品、市场或品类不匹配：{raw_id}")
                payload = ({"rating": item.rating, "variant": item.variant}
                           if kind == "review" else {"title": item.title,
                                                    "valid_from": item.valid_from})
                payload["data_kind"] = item.data_kind
                body = item.content.strip() if kind == "review" else item.text.strip()
                if not body:
                    raise ValueError("证据正文不能为空白")
                content_hash = digest({"text": body, "payload": payload,
                                       "source_url": item.source_url,
                                       "observed_at": item.observed_at.isoformat(),
                                       "market": item.market, "category": item.category,
                                       "product_id": product_id,
                                       "version": item.version if kind == "rule" else "import-v1"})
                existing = session.get(Evidence, identity)
                if existing:
                    if existing.content_hash != content_hash:
                        raise ValueError(f"证据已存在且内容不同，请显式更新：{identity}")
                    continue
                session.add(Evidence(
                    id=identity, product_id=product_id, import_batch_id=batch.id,
                    evidence_kind=kind, source_type="user_import", source_record_id=raw_id,
                    source_url=item.source_url, market=item.market, category=item.category,
                    observed_at=item.observed_at, content_hash=content_hash,
                    content_version=item.version if kind == "rule" else "import-v1",
                    text=body, payload=payload,
                ))
                session.add(EvidenceState(evidence_id=identity, active=True, generation=1))
                session.add(IndexEvent(id=str(uuid4()), evidence_id=identity))
                counts[kind + "s"] += 1
        batch.summary = counts
        return {"batch_id": batch.id, "status": "imported", **counts}
