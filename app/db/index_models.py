"""证据可见性、索引 outbox、版本 manifest 及运行笔记。"""

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class EvidenceState(Base):
    """删除先在数据库不可见，再异步清理向量。"""

    __tablename__ = "evidence_state"
    evidence_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    generation: Mapped[int] = mapped_column(Integer, default=1)


class IndexEvent(Base):
    """与证据修改同事务保存的事件，重复投递按当前版本合并。"""

    __tablename__ = "index_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    evidence_id: Mapped[str] = mapped_column(String(80), index=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(String(100))
    retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class VectorManifest(Base):
    """每个证据在每个向量空间的当前 chunk，供对账和删除。"""

    __tablename__ = "vector_manifests"
    evidence_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    collection: Mapped[str] = mapped_column(String(120), primary_key=True)
    chunk_id: Mapped[str] = mapped_column(String(64))
    content_hash: Mapped[str] = mapped_column(String(64))


class ResearchNote(Base):
    """运行内笔记，重启保留，不使用任意文件路径。"""

    __tablename__ = "research_notes"
    run_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(80), primary_key=True)
    content: Mapped[str] = mapped_column(Text)
    evidence_ids: Mapped[list] = mapped_column(JSON)
