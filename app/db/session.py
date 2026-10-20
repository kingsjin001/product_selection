"""SQLAlchemy 引擎与会话工厂；每进程复用连接池。"""

from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings


class Base(DeclarativeBase):
    """所有 ORM 模型共享的声明式基类。"""

    pass


@lru_cache
def get_engine():
    """按当前配置创建带连接存活检查的同步 PostgreSQL 引擎。"""
    # pool_pre_ping 会在复用连接前验证可用性，降低 Docker 重启后的失效连接报错。
    return create_engine(get_settings().database_url, pool_pre_ping=True)


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    """返回独立会话工厂；调用方负责业务事务的提交、回滚和关闭。"""
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)
