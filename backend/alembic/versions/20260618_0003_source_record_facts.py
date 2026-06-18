"""queryable source record facts

Revision ID: 20260618_0003
Revises: 20260618_0002
Create Date: 2026-06-18 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260618_0003"
down_revision: str | None = "20260618_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def utc_ts(name: str, nullable: bool = False) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def upgrade() -> None:
    op.create_table(
        "source_record_facts",
        sa.Column("fact_code", sa.String(length=32), primary_key=True),
        sa.Column("source_record_code", sa.String(length=32), sa.ForeignKey("source_records.source_record_code"), nullable=False),
        sa.Column("source_code", sa.String(length=32), sa.ForeignKey("sources.source_code"), nullable=False),
        sa.Column("entity_kind", sa.String(length=40), nullable=False),
        sa.Column("product_code", sa.String(length=32), sa.ForeignKey("products.product_code"), nullable=True),
        sa.Column("ingredient_code", sa.String(length=32), sa.ForeignKey("ingredients.ingredient_code"), nullable=True),
        sa.Column("fact_type", sa.String(length=80), nullable=False),
        sa.Column("field_name", sa.String(length=120), nullable=False),
        sa.Column("label", sa.String(length=240), nullable=True),
        sa.Column("value_text", sa.Text(), nullable=True),
        sa.Column("value_json", sa.JSON(), nullable=False),
        sa.Column("normalized_value", sa.String(length=500), nullable=True),
        sa.Column("source_url", sa.String(length=800), nullable=True),
        sa.Column("confidence_score", sa.Float(), nullable=False, server_default="0.8"),
        utc_ts("created_at"),
        utc_ts("updated_at"),
    )
    op.create_index("ix_source_record_facts_record", "source_record_facts", ["source_record_code"])
    op.create_index("ix_source_record_facts_source", "source_record_facts", ["source_code"])
    op.create_index("ix_source_record_facts_entity", "source_record_facts", ["entity_kind"])
    op.create_index("ix_source_record_facts_product", "source_record_facts", ["product_code"])
    op.create_index("ix_source_record_facts_ingredient", "source_record_facts", ["ingredient_code"])
    op.create_index("ix_source_record_facts_type", "source_record_facts", ["fact_type"])
    op.create_index("ix_source_record_facts_field", "source_record_facts", ["field_name"])
    op.create_index("ix_source_record_facts_normalized", "source_record_facts", ["normalized_value"])
    op.create_index(
        "ix_source_record_facts_record_field_value",
        "source_record_facts",
        ["source_record_code", "entity_kind", "field_name", "normalized_value"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_table("source_record_facts")
