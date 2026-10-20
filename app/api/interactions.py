"""第七期人工复核与记忆管理接口，供个人本地工作台使用。"""

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.config import get_settings
from app.db.interaction_models import MemoryCandidate
from app.db.session import get_session_factory
from app.services.memory import (
    Preferences,
    decide_candidate,
    preference_snapshot,
    save_preferences,
)
from app.services.reviews import decide_review, get_review
from app.services.tasks import TaskConflict

router = APIRouter(prefix="/api", tags=["人工复核与记忆"])


class ReviewDecision(BaseModel):
    """决定绑定用户看过的草稿摘要，防止误批过期页面。"""
    draft_hash: str = Field(min_length=64, max_length=64)
    action: Literal["approve", "reject", "request_changes"]
    feedback: str = Field(default="", max_length=500)


class CandidateDecision(BaseModel):
    """可先编辑候选内容，再一次性确认完整偏好。"""
    action: Literal["confirm", "ignore"]
    content: Preferences | None = None


@router.get("/tasks/{run_id}/review")
def review(run_id: str):
    """读取待审草稿及理由，与已发布报告接口区分。"""
    try:
        return get_review(get_session_factory(), run_id)
    except ValueError as error:
        raise HTTPException(404, str(error)) from error


@router.post("/tasks/{run_id}/review")
def decide(run_id: str, request: ReviewDecision):
    """批准入队，拒绝终止，要求修改返回独立后继任务。"""
    try:
        return decide_review(get_session_factory(), get_settings(), run_id,
                             **request.model_dump())
    except TaskConflict as error:
        raise HTTPException(409, str(error)) from error
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@router.get("/preferences")
def preferences():
    """查看本地单用户有效偏好及版本。"""
    with get_session_factory()() as session:
        return preference_snapshot(session)


@router.put("/preferences")
def update_preferences(request: Preferences):
    """用户明确保存的设置立即生效，无需重复候选确认。"""
    try:
        with get_session_factory().begin() as session:
            return save_preferences(session, request.model_dump())
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@router.delete("/preferences")
def delete_preferences():
    """清空内容但保留递增版本，历史任务审计快照保持不变。"""
    with get_session_factory().begin() as session:
        return save_preferences(session, Preferences().model_dump())


@router.get("/memory-candidates")
def candidates():
    """只展示待确认候选，来源运行可回查。"""
    with get_session_factory()() as session:
        rows = session.scalars(select(MemoryCandidate).where(
            MemoryCandidate.status == "pending")).all()
        return [{"id": row.id, "run_id": row.run_id, "content": row.content,
                 "reason": row.reason, "status": row.status} for row in rows]


@router.post("/memory-candidates/{identity}/decision")
def decide_memory(identity: str, request: CandidateDecision):
    """确认、修改后确认或忽略；候选本身不影响研究。"""
    try:
        return decide_candidate(get_session_factory(), identity, request.action,
                                 request.content.model_dump() if request.content else None)
    except ValueError as error:
        raise HTTPException(409, str(error)) from error
