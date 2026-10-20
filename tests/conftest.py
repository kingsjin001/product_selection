"""将 PostgreSQL JSONB 映射到测试 SQLite 的 JSON 存储类型。"""

from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles


@compiles(JSONB, "sqlite")
def compile_jsonb(element, compiler, **kw):
    """仅影响 SQLite 测试方言，不改变 PostgreSQL 迁移。"""
    return "JSON"
