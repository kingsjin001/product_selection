"""第二期运行快照、报告及调用账本。"""

import sqlalchemy as sa
from alembic import op

revision = "20261021_02"
down_revision = "20261019_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """仅新增第二期表，不修改已有商品和证据。"""
    op.create_table(
        "analysis_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("request", sa.JSON(), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("versions", sa.JSON(), nullable=False),
        sa.Column("model_calls", sa.Integer(), nullable=False),
        sa.Column("tool_calls", sa.Integer(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "analysis_reports",
        sa.Column("run_id", sa.String(36), sa.ForeignKey("analysis_runs.id"), primary_key=True),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("markdown", sa.Text(), nullable=False),
    )
    op.create_table(
        "analysis_calls",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("analysis_runs.id"), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("latency_ms", sa.Integer()),
        sa.Column("details", sa.JSON(), nullable=False),
    )
    op.create_index("ix_analysis_calls_run_id", "analysis_calls", ["run_id"])


def downgrade() -> None:
    """逆序回退第二期新增表；仅供明确要求回退时使用。"""
    op.drop_table("analysis_calls")
    op.drop_table("analysis_reports")
    op.drop_table("analysis_runs")
