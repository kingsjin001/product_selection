"""第一期证据数据表。

Revision ID: 20261019_01
Revises:
Create Date: 2026-10-19 18:20:00
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261019_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """创建导入批次、商品和可追溯证据表。"""
    op.create_table(
        "import_batches",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("manifest_hash", sa.String(length=64), nullable=False),
        sa.Column("source_name", sa.String(length=120), nullable=False),
        sa.Column("imported_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("summary", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("manifest_hash"),
    )
    op.create_table(
        "products",
        sa.Column("id", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("market", sa.String(length=12), nullable=False),
        sa.Column("category", sa.String(length=120), nullable=False),
        sa.Column("specifications", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("source_url", sa.String(length=1024)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_products_category", "products", ["category"])
    op.create_index("ix_products_market", "products", ["market"])
    op.create_table(
        "evidence",
        sa.Column("id", sa.String(length=80), nullable=False),
        sa.Column("product_id", sa.String(length=80)),
        sa.Column("import_batch_id", sa.String(length=36), nullable=False),
        sa.Column("evidence_kind", sa.String(length=32), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("source_record_id", sa.String(length=120), nullable=False),
        sa.Column("source_url", sa.String(length=1024)),
        sa.Column("market", sa.String(length=12), nullable=False),
        sa.Column("category", sa.String(length=120), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True)),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("content_version", sa.String(length=64), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["import_batch_id"], ["import_batches.id"]),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_type", "source_record_id", "content_hash", name="uq_evidence_source"
        ),
    )
    op.create_index("ix_evidence_lookup", "evidence", ["evidence_kind", "market", "category"])


def downgrade() -> None:
    """按外键依赖的反向顺序删除第一期数据表。"""
    op.drop_index("ix_evidence_lookup", table_name="evidence")
    op.drop_table("evidence")
    op.drop_index("ix_products_market", table_name="products")
    op.drop_index("ix_products_category", table_name="products")
    op.drop_table("products")
    op.drop_table("import_batches")
