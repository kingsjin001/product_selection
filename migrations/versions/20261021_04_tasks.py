"""后台任务、投递与持久事件。"""

import sqlalchemy as sa
from alembic import op

revision = "20261021_04"
down_revision = "20261021_03"
branch_labels = depends_on = None


def upgrade():
    """迁移只创建新表，不删除前期数据或检查点。"""
    op.create_table(
        "tasks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("idempotency_key", sa.String(120), nullable=False, unique=True),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("stage", sa.String(40), nullable=False),
        sa.Column("epoch", sa.Integer, nullable=False),
        sa.Column("attempts", sa.Integer, nullable=False),
        sa.Column("event_seq", sa.Integer, nullable=False),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("deadline_at", sa.DateTime(timezone=True)),
        sa.Column("error", sa.String(100)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
    )
    op.create_table(
        "task_dispatches",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("task_id", sa.String(36), nullable=False, index=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("attempts", sa.Integer, nullable=False),
        sa.Column("retry_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "task_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("task_id", sa.String(36), nullable=False, index=True),
        sa.Column("seq", sa.Integer, nullable=False),
        sa.Column("stage", sa.String(40), nullable=False),
        sa.Column("type", sa.String(40), nullable=False),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("payload", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.UniqueConstraint("task_id", "seq"),
    )


def downgrade():
    """仅供明确需要回滚 schema 的开发场景。"""
    op.drop_table("task_events")
    op.drop_table("task_dispatches")
    op.drop_table("tasks")
