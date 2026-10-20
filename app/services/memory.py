"""用户可管理的结构化偏好；候选记忆不自动生效。"""

from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.db.interaction_models import MemoryCandidate, UserPreference


class Preferences(BaseModel):
    """只保存偏好字段，禁止把任意指令或市场结论写入长期记忆。"""

    model_config = ConfigDict(extra="forbid")
    target_market: str = Field(default="", pattern=r"^([A-Z]{2})?$")
    excluded_categories: list[str] = Field(default_factory=list, max_length=20)
    response_language: str = Field(default="中文", max_length=30)


def preference_snapshot(session):
    """冻结当前有效版本；偏好删除不追溯修改已有报告。"""
    row = session.get(UserPreference, "local")
    return {"version": row.version, "content": row.content} if row else {
        "version": 0, "content": Preferences().model_dump(),
    }


def save_preferences(session, value):
    """在调用者事务内保存完整偏好，并递增审计版本。"""
    content = Preferences.model_validate(value).model_dump()
    if any(not item.strip() or len(item) > 80 for item in content["excluded_categories"]):
        raise ValueError("排除品类须为 1～80 字")
    row = session.scalar(select(UserPreference).where(
        UserPreference.id == "local").with_for_update())
    if row is None:
        row = UserPreference(id="local", version=1, content=content)
        session.add(row)
    else:
        row.content, row.version = content, row.version + 1
    return {"version": row.version, "content": content}


def propose_candidate(session, run_id, content, reason):
    """模型建议只落为 pending；不允许将空候选或无来源建议直接应用。"""
    value = Preferences.model_validate(content).model_dump()
    identity = str(uuid4())
    session.add(MemoryCandidate(id=identity, run_id=run_id, content=value,
                                reason=reason[:2000], status="pending"))
    return identity


def decide_candidate(factory, identity, action, content=None):
    """确认支持用户编辑；同一决定重复提交幂等，相反决定拒绝。"""
    with factory.begin() as session:
        row = session.scalar(select(MemoryCandidate).where(
            MemoryCandidate.id == identity).with_for_update())
        if row is None:
            raise ValueError("候选记忆不存在")
        value = Preferences.model_validate(content or row.content).model_dump()
        decision = {"action": action, "content": value if action == "confirm" else None}
        if row.status != "pending":
            if row.decision != decision:
                raise ValueError("候选记忆已经处理")
            return {"id": identity, "status": row.status}
        if action == "confirm":
            save_preferences(session, value)
        elif action != "ignore":
            raise ValueError("仅支持 confirm 或 ignore")
        row.status, row.decision = action, decision
        return {"id": identity, "status": row.status}
