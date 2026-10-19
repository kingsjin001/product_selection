"""${message}。

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

# Alembic 用这些标识维护迁移链路。
revision: str = ${repr(up_revision)}
down_revision: Union[str, Sequence[str], None] = ${repr(down_revision)}
branch_labels: Union[str, Sequence[str], None] = ${repr(branch_labels)}
depends_on: Union[str, Sequence[str], None] = ${repr(depends_on)}


def upgrade() -> None:
    """执行当前版本的数据库结构升级。"""
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    """回退当前版本引入的数据库结构变更。"""
    ${downgrades if downgrades else "pass"}

