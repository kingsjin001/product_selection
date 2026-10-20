"""证据详情、混合检索和修改接口；适用于本地开发，不公开到互联网。"""

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.db.index_models import EvidenceState
from app.db.models import Evidence
from app.db.session import get_session_factory
from app.services.hybrid_search import search_evidence
from app.services.indexing import change_evidence

router = APIRouter(prefix="/api/evidence", tags=["证据"])


class EvidenceSearch(BaseModel):
    """检索类型和过滤条件。"""

    query: str = Field(min_length=1, max_length=1000)
    kind: Literal["rule", "review"] = "rule"
    market: str = "US"
    category: str = ""
    product_id: str = ""
    top_k: int = Field(default=5, ge=1, le=20)
    as_of: datetime | None = None


class EvidenceEdit(BaseModel):
    """显式修改证据正文，索引更新由 outbox 同步处理。"""

    content: str = Field(min_length=1, max_length=8000)


@router.post("/search")
def search(request: EvidenceSearch):
    """检索前确保已建立第三期索引；服务不可用不能伪装成无结果。"""
    try:
        return {"data": search_evidence(
            get_session_factory(), get_settings(), **request.model_dump(),
        )}
    except RuntimeError as error:
        raise HTTPException(503, str(error)) from error


@router.get("/{evidence_id}")
def detail(evidence_id: str):
    """读取来源、正文和版本，供前端引用展开。"""
    with get_session_factory()() as session:
        row = session.get(Evidence, evidence_id)
        if row is None:
            raise HTTPException(404, "证据不存在")
        state = session.get(EvidenceState, evidence_id)
        return {"id": row.id, "text": row.text, "version": row.content_version,
                "source_url": row.source_url, "payload": row.payload,
                "active": state.active if state else True}


@router.patch("/{evidence_id}")
def edit(evidence_id: str, request: EvidenceEdit):
    """登记新版本及待同步事件。"""
    try:
        change_evidence(get_session_factory(), evidence_id, content=request.content)
    except ValueError as error:
        raise HTTPException(404, str(error)) from error
    return {"status": "queued"}


@router.delete("/{evidence_id}")
def remove(evidence_id: str):
    """软删除后立即在第三期检索中不可见，实际向量随后清理。"""
    try:
        change_evidence(get_session_factory(), evidence_id, delete=True)
    except ValueError as error:
        raise HTTPException(404, str(error)) from error
    return {"status": "queued"}
