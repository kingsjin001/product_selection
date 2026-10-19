"""SQLAlchemy 引擎与会话工厂。"""

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings


class Base(DeclarativeBase):
    """所有 ORM 模型共享的声明式基类。"""

    pass


def get_engine():
    """创建带连接存活检查的同步 PostgreSQL 引擎。"""
    return create_engine(get_settings().database_url, pool_pre_ping=True)


def get_session_factory() -> sessionmaker[Session]:
    """返回独立会话工厂，调用方负责提交、回滚和关闭会话。"""
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)
