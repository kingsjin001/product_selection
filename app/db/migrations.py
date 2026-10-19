"""宿主机 CLI 使用的 Alembic 迁移封装。"""

from pathlib import Path

from alembic import command
from alembic.config import Config


def upgrade_head() -> None:
    """将仓库中的全部迁移应用到当前配置的 PostgreSQL 数据库。"""
    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "alembic.ini"))
    command.upgrade(config, "head")
