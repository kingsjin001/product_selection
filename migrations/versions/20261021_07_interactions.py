"""第七期独立表，迁移字段固定，不依赖未来 ORM 模型变更。"""

import sqlalchemy as sa
from alembic import op

revision = "20261021_07"
down_revision = "20261021_05"
branch_labels = depends_on = None


def upgrade():
    """新增复核、偏好、候选和会话表，旧数据保持不变。"""
    op.create_table(
        "report_reviews",
        sa.Column("run_id", sa.String(36), primary_key=True),
        sa.Column("draft_hash", sa.String(64), nullable=False),
        sa.Column("content", sa.JSON, nullable=False),
        sa.Column("reasons", sa.JSON, nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("decision", sa.JSON),
        sa.Column("remaining_seconds", sa.Float),
        sa.Column("waiting_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_table(
        "user_preferences",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("content", sa.JSON, nullable=False),
    )
    op.create_table(
        "memory_candidates",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("content", sa.JSON, nullable=False),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("decision", sa.JSON),
    )
    op.create_table(
        "report_conversations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), nullable=False, index=True),
        sa.Column("report_hash", sa.String(64), nullable=False),
        sa.Column("history", sa.JSON, nullable=False),
        sa.Column("busy_token", sa.String(36)),
        sa.Column("busy_until", sa.DateTime(timezone=True)),
    )


def downgrade():
    """显式降级会删除第七期交互历史，请先备份。"""
    for name in ("report_conversations", "memory_candidates", "user_preferences", "report_reviews"):
        op.drop_table(name)
