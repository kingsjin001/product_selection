"""第七期人工复核、单用户偏好及报告会话的持久记录。"""

from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class ReportReview(Base):
    """一个运行只有一份草稿；修改请求创建新运行而不覆盖原草稿。"""

    __tablename__ = "report_reviews"
    run_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    draft_hash: Mapped[str] = mapped_column(String(64))
    content: Mapped[dict] = mapped_column(JSON)
    reasons: Mapped[list] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(24), default="pending")
    decision: Mapped[dict | None] = mapped_column(JSON)
    remaining_seconds: Mapped[float | None] = mapped_column(Float)
    waiting_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UserPreference(Base):
    """个人项目使用唯一 local 配置；不声称具备多租户权限隔离。"""

    __tablename__ = "user_preferences"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    content: Mapped[dict] = mapped_column(JSON)


class MemoryCandidate(Base):
    """从追问推断的偏好候选，只有用户确认才写入有效偏好。"""

    __tablename__ = "memory_candidates"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(36))
    content: Mapped[dict] = mapped_column(JSON)
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    decision: Mapped[dict | None] = mapped_column(JSON)


class ReportConversation(Base):
    """会话绑定报告，短租约防止并行追问乱序且不长时间持有数据库锁。"""

    __tablename__ = "report_conversations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(36), index=True)
    report_hash: Mapped[str] = mapped_column(String(64))
    history: Mapped[list] = mapped_column(JSON, default=list)
    busy_token: Mapped[str | None] = mapped_column(String(36))
    busy_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
