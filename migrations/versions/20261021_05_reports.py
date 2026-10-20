"""报告导出制品与独立追问历史。"""

import sqlalchemy as sa
from alembic import op

revision = "20261021_05"
down_revision = "20261021_04"
branch_labels = depends_on = None


def upgrade():
    """导出内容存储为字节，避免外部文件生命周期与记录脱节。"""
    op.create_table(
        "report_exports",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("run_id", sa.String(36), nullable=False, index=True),
        sa.Column("format", sa.String(10), nullable=False),
        sa.Column("report_hash", sa.String(64), nullable=False),
        sa.Column("template_version", sa.String(40), nullable=False),
        sa.Column("file_hash", sa.String(64), nullable=False),
        sa.Column("content", sa.LargeBinary, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    op.create_table(
        "report_questions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), nullable=False, index=True),
        sa.Column("report_hash", sa.String(64), nullable=False),
        sa.Column("request", sa.JSON, nullable=False),
        sa.Column("response", sa.JSON),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("model", sa.String(120)),
        sa.Column("input_tokens", sa.Integer, nullable=False),
        sa.Column("output_tokens", sa.Integer, nullable=False),
        sa.Column("latency_ms", sa.Integer, nullable=False),
        sa.Column("error", sa.String(100)),
    )


def downgrade():
    """显式回滚只删除第五期表。"""
    op.drop_table("report_questions")
    op.drop_table("report_exports")
