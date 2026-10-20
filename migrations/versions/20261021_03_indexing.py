"""第三期向量同步、可见性和研究笔记。"""

import sqlalchemy as sa
from alembic import op

revision = "20261021_03"
down_revision = "20261021_02"
branch_labels = None
depends_on = None


def upgrade():
    """新增索引事务表，不改动第一期集合。"""
    op.create_table(
        "evidence_state",
        sa.Column("evidence_id", sa.String(80), primary_key=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
    )
    op.create_table(
        "index_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("evidence_id", sa.String(80), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("error", sa.String(100)),
        sa.Column("retry_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_index_events_evidence_id", "index_events", ["evidence_id"])
    op.create_table(
        "vector_manifests",
        sa.Column("evidence_id", sa.String(80), primary_key=True),
        sa.Column("collection", sa.String(120), primary_key=True),
        sa.Column("chunk_id", sa.String(64), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
    )
    op.create_table(
        "research_notes",
        sa.Column("run_id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(80), primary_key=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("evidence_ids", sa.JSON(), nullable=False),
    )


def downgrade():
    """逆序回退第三期表。"""
    for name in ("research_notes", "vector_manifests", "index_events", "evidence_state"):
        op.drop_table(name)
