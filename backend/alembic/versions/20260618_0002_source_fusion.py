"""source fusion and canonical terms

Revision ID: 20260618_0002
Revises: 20260617_0001
Create Date: 2026-06-18 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260618_0002"
down_revision: str | None = "20260617_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def utc_ts(name: str, nullable: bool = False) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def upgrade() -> None:
    op.create_table(
        "product_source_links",
        sa.Column("product_source_link_code", sa.String(length=32), primary_key=True),
        sa.Column("product_code", sa.String(length=32), sa.ForeignKey("products.product_code"), nullable=False),
        sa.Column("source_record_code", sa.String(length=32), sa.ForeignKey("source_records.source_record_code"), nullable=False),
        sa.Column("source_code", sa.String(length=32), sa.ForeignKey("sources.source_code"), nullable=False),
        sa.Column("external_id", sa.String(length=300), nullable=False),
        sa.Column("source_url", sa.String(length=800), nullable=True),
        sa.Column("match_method", sa.String(length=80), nullable=False),
        sa.Column("match_confidence", sa.Float(), nullable=False, server_default="1.0"),
        utc_ts("source_updated_at", True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        utc_ts("created_at"),
        utc_ts("updated_at"),
    )
    op.create_index("ix_product_source_links_product", "product_source_links", ["product_code"])
    op.create_index("ix_product_source_links_record", "product_source_links", ["source_record_code"])
    op.create_index("ix_product_source_links_source", "product_source_links", ["source_code"])
    op.create_index(
        "ix_product_source_links_product_record",
        "product_source_links",
        ["product_code", "source_record_code"],
        unique=True,
    )

    op.create_table(
        "ingredient_source_links",
        sa.Column("ingredient_source_link_code", sa.String(length=32), primary_key=True),
        sa.Column("ingredient_code", sa.String(length=32), sa.ForeignKey("ingredients.ingredient_code"), nullable=False),
        sa.Column("source_record_code", sa.String(length=32), sa.ForeignKey("source_records.source_record_code"), nullable=False),
        sa.Column("source_code", sa.String(length=32), sa.ForeignKey("sources.source_code"), nullable=False),
        sa.Column("external_id", sa.String(length=300), nullable=False),
        sa.Column("source_url", sa.String(length=800), nullable=True),
        sa.Column("match_method", sa.String(length=80), nullable=False),
        sa.Column("match_confidence", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        utc_ts("created_at"),
        utc_ts("updated_at"),
    )
    op.create_index("ix_ingredient_source_links_ingredient", "ingredient_source_links", ["ingredient_code"])
    op.create_index("ix_ingredient_source_links_record", "ingredient_source_links", ["source_record_code"])
    op.create_index("ix_ingredient_source_links_source", "ingredient_source_links", ["source_code"])
    op.create_index(
        "ix_ingredient_source_links_ingredient_record",
        "ingredient_source_links",
        ["ingredient_code", "source_record_code"],
        unique=True,
    )

    op.create_table(
        "canonical_terms",
        sa.Column("term_code", sa.String(length=32), primary_key=True),
        sa.Column("term_type", sa.String(length=80), nullable=False),
        sa.Column("slug", sa.String(length=220), nullable=False),
        sa.Column("label", sa.String(length=240), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        utc_ts("created_at"),
        utc_ts("updated_at"),
    )
    op.create_index("ix_canonical_terms_type", "canonical_terms", ["term_type"])
    op.create_index("ix_canonical_terms_slug", "canonical_terms", ["slug"])
    op.create_index("ix_canonical_terms_type_slug", "canonical_terms", ["term_type", "slug"], unique=True)

    op.create_table(
        "term_aliases",
        sa.Column("alias_code", sa.String(length=32), primary_key=True),
        sa.Column("term_code", sa.String(length=32), sa.ForeignKey("canonical_terms.term_code"), nullable=False),
        sa.Column("source_code", sa.String(length=32), sa.ForeignKey("sources.source_code"), nullable=True),
        sa.Column("alias", sa.String(length=240), nullable=False),
        sa.Column("normalized_alias", sa.String(length=260), nullable=False),
        utc_ts("created_at"),
    )
    op.create_index("ix_term_aliases_term", "term_aliases", ["term_code"])
    op.create_index("ix_term_aliases_normalized", "term_aliases", ["normalized_alias"])
    op.create_index(
        "ix_term_aliases_term_source_alias",
        "term_aliases",
        ["term_code", "source_code", "normalized_alias"],
        unique=True,
    )

    op.create_table(
        "product_term_links",
        sa.Column("product_term_link_code", sa.String(length=32), primary_key=True),
        sa.Column("product_code", sa.String(length=32), sa.ForeignKey("products.product_code"), nullable=False),
        sa.Column("term_code", sa.String(length=32), sa.ForeignKey("canonical_terms.term_code"), nullable=False),
        sa.Column("source_record_code", sa.String(length=32), sa.ForeignKey("source_records.source_record_code"), nullable=False),
        sa.Column("source_code", sa.String(length=32), sa.ForeignKey("sources.source_code"), nullable=False),
        sa.Column("raw_value", sa.String(length=300), nullable=False),
        sa.Column("confidence_score", sa.Float(), nullable=False, server_default="0.8"),
        utc_ts("created_at"),
    )
    op.create_index("ix_product_term_links_product", "product_term_links", ["product_code"])
    op.create_index("ix_product_term_links_term", "product_term_links", ["term_code"])
    op.create_index("ix_product_term_links_record", "product_term_links", ["source_record_code"])
    op.create_index("ix_product_term_links_source", "product_term_links", ["source_code"])
    op.create_index(
        "ix_product_term_links_product_term_record",
        "product_term_links",
        ["product_code", "term_code", "source_record_code"],
        unique=True,
    )

    op.create_table(
        "ingredient_term_links",
        sa.Column("ingredient_term_link_code", sa.String(length=32), primary_key=True),
        sa.Column("ingredient_code", sa.String(length=32), sa.ForeignKey("ingredients.ingredient_code"), nullable=False),
        sa.Column("term_code", sa.String(length=32), sa.ForeignKey("canonical_terms.term_code"), nullable=False),
        sa.Column("source_record_code", sa.String(length=32), sa.ForeignKey("source_records.source_record_code"), nullable=False),
        sa.Column("source_code", sa.String(length=32), sa.ForeignKey("sources.source_code"), nullable=False),
        sa.Column("raw_value", sa.String(length=300), nullable=False),
        sa.Column("confidence_score", sa.Float(), nullable=False, server_default="0.8"),
        utc_ts("created_at"),
    )
    op.create_index("ix_ingredient_term_links_ingredient", "ingredient_term_links", ["ingredient_code"])
    op.create_index("ix_ingredient_term_links_term", "ingredient_term_links", ["term_code"])
    op.create_index("ix_ingredient_term_links_record", "ingredient_term_links", ["source_record_code"])
    op.create_index("ix_ingredient_term_links_source", "ingredient_term_links", ["source_code"])
    op.create_index(
        "ix_ingredient_term_links_ingredient_term_record",
        "ingredient_term_links",
        ["ingredient_code", "term_code", "source_record_code"],
        unique=True,
    )


def downgrade() -> None:
    for table in [
        "ingredient_term_links",
        "product_term_links",
        "term_aliases",
        "canonical_terms",
        "ingredient_source_links",
        "product_source_links",
    ]:
        op.drop_table(table)
