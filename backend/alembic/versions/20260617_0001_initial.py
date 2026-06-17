"""initial schema

Revision ID: 20260617_0001
Revises:
Create Date: 2026-06-17 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260617_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def utc_ts(name: str, nullable: bool = False) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def upgrade() -> None:
    op.create_table(
        "sources",
        sa.Column("source_code", sa.String(length=32), primary_key=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("kind", sa.String(length=80), nullable=False),
        sa.Column("homepage_url", sa.String(length=500), nullable=True),
        sa.Column("license_name", sa.String(length=160), nullable=True),
        sa.Column("terms_url", sa.String(length=500), nullable=True),
        sa.Column("reliability", sa.String(length=80), nullable=False, server_default="unknown"),
        utc_ts("created_at"),
        utc_ts("updated_at"),
    )
    op.create_table(
        "source_records",
        sa.Column("source_record_code", sa.String(length=32), primary_key=True),
        sa.Column("source_code", sa.String(length=32), sa.ForeignKey("sources.source_code"), nullable=False),
        sa.Column("external_id", sa.String(length=300), nullable=False),
        sa.Column("record_type", sa.String(length=80), nullable=False),
        sa.Column("source_url", sa.String(length=800), nullable=True),
        sa.Column("content_hash", sa.String(length=80), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        utc_ts("fetched_at"),
        utc_ts("created_at"),
    )
    op.create_index("ix_source_records_source_external", "source_records", ["source_code", "external_id"], unique=True)

    op.create_table(
        "brands",
        sa.Column("brand_code", sa.String(length=32), primary_key=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("normalized_name", sa.String(length=220), nullable=False, unique=True),
        sa.Column("source_record_code", sa.String(length=32), sa.ForeignKey("source_records.source_record_code"), nullable=True),
        utc_ts("created_at"),
        utc_ts("updated_at"),
    )
    op.create_table(
        "categories",
        sa.Column("category_code", sa.String(length=32), primary_key=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("slug", sa.String(length=220), nullable=False, unique=True),
        utc_ts("created_at"),
        utc_ts("updated_at"),
    )
    op.create_table(
        "products",
        sa.Column("product_code", sa.String(length=32), primary_key=True),
        sa.Column("barcode", sa.String(length=80), nullable=True, unique=True),
        sa.Column("name", sa.String(length=300), nullable=False),
        sa.Column("normalized_name", sa.String(length=340), nullable=False),
        sa.Column("brand_code", sa.String(length=32), sa.ForeignKey("brands.brand_code"), nullable=True),
        sa.Column("source_record_code", sa.String(length=32), sa.ForeignKey("source_records.source_record_code"), nullable=True),
        sa.Column("category_text", sa.Text(), nullable=True),
        sa.Column("ingredient_text", sa.Text(), nullable=True),
        sa.Column("data_quality_warnings", sa.JSON(), nullable=False),
        sa.Column("confidence_score", sa.Float(), nullable=False, server_default="0.5"),
        utc_ts("last_source_update_at", True),
        utc_ts("created_at"),
        utc_ts("updated_at"),
    )
    op.create_index("ix_products_name", "products", ["normalized_name"])
    op.create_table(
        "product_categories",
        sa.Column("product_code", sa.String(length=32), sa.ForeignKey("products.product_code"), primary_key=True),
        sa.Column("category_code", sa.String(length=32), sa.ForeignKey("categories.category_code"), primary_key=True),
    )
    op.create_table(
        "product_images",
        sa.Column("image_code", sa.String(length=32), primary_key=True),
        sa.Column("product_code", sa.String(length=32), sa.ForeignKey("products.product_code"), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("url", sa.String(length=800), nullable=True),
        sa.Column("local_path", sa.String(length=800), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("source_record_code", sa.String(length=32), sa.ForeignKey("source_records.source_record_code"), nullable=True),
        sa.Column("embedding_status", sa.String(length=40), nullable=False, server_default="pending"),
        utc_ts("created_at"),
        utc_ts("updated_at"),
    )

    op.create_table(
        "ingredients",
        sa.Column("ingredient_code", sa.String(length=32), primary_key=True),
        sa.Column("canonical_name", sa.String(length=260), nullable=False),
        sa.Column("normalized_name", sa.String(length=280), nullable=False, unique=True),
        sa.Column("inci_name", sa.String(length=260), nullable=True),
        sa.Column("cas_number", sa.String(length=80), nullable=True),
        sa.Column("ec_number", sa.String(length=80), nullable=True),
        sa.Column("pubchem_cid", sa.String(length=80), nullable=True),
        sa.Column("functions", sa.JSON(), nullable=False),
        sa.Column("regulatory_status", sa.String(length=120), nullable=False, server_default="unknown"),
        sa.Column("source_record_code", sa.String(length=32), sa.ForeignKey("source_records.source_record_code"), nullable=True),
        utc_ts("created_at"),
        utc_ts("updated_at"),
    )
    op.create_table(
        "ingredient_synonyms",
        sa.Column("synonym_code", sa.String(length=32), primary_key=True),
        sa.Column("ingredient_code", sa.String(length=32), sa.ForeignKey("ingredients.ingredient_code"), nullable=False),
        sa.Column("name", sa.String(length=260), nullable=False),
        sa.Column("normalized_name", sa.String(length=280), nullable=False),
        utc_ts("created_at"),
    )
    op.create_index("ix_ingredient_synonyms_normalized", "ingredient_synonyms", ["normalized_name"])
    op.create_table(
        "product_ingredients",
        sa.Column("product_ingredient_code", sa.String(length=32), primary_key=True),
        sa.Column("product_code", sa.String(length=32), sa.ForeignKey("products.product_code"), nullable=False),
        sa.Column("ingredient_code", sa.String(length=32), sa.ForeignKey("ingredients.ingredient_code"), nullable=False),
        sa.Column("raw_name", sa.String(length=260), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=True),
        sa.Column("percent_min", sa.Float(), nullable=True),
        sa.Column("percent_max", sa.Float(), nullable=True),
        sa.Column("percent_estimate", sa.Float(), nullable=True),
        sa.Column("source_record_code", sa.String(length=32), sa.ForeignKey("source_records.source_record_code"), nullable=True),
        utc_ts("created_at"),
    )
    op.create_index("ix_product_ingredients_product_ingredient", "product_ingredients", ["product_code", "ingredient_code"], unique=True)

    op.create_table(
        "risk_rules",
        sa.Column("risk_rule_code", sa.String(length=32), primary_key=True),
        sa.Column("ingredient_code", sa.String(length=32), sa.ForeignKey("ingredients.ingredient_code"), nullable=False),
        sa.Column("source_record_code", sa.String(length=32), sa.ForeignKey("source_records.source_record_code"), nullable=False),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("severity", sa.String(length=40), nullable=False),
        sa.Column("severity_score", sa.Integer(), nullable=False),
        sa.Column("side_effects", sa.JSON(), nullable=False),
        sa.Column("applies_to", sa.JSON(), nullable=False),
        sa.Column("evidence_kind", sa.String(length=80), nullable=False),
        sa.Column("confidence_score", sa.Float(), nullable=False),
        sa.Column("version", sa.String(length=40), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        utc_ts("created_at"),
        utc_ts("updated_at"),
    )
    op.create_table(
        "risk_evaluations",
        sa.Column("evaluation_code", sa.String(length=32), primary_key=True),
        sa.Column("product_code", sa.String(length=32), sa.ForeignKey("products.product_code"), nullable=False),
        sa.Column("profile", sa.JSON(), nullable=False),
        sa.Column("severity", sa.String(length=40), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("matched_rule_codes", sa.JSON(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        utc_ts("created_at"),
    )

    op.create_table(
        "scan_jobs",
        sa.Column("scan_code", sa.String(length=32), primary_key=True),
        sa.Column("upload_filename", sa.String(length=300), nullable=False),
        sa.Column("image_path", sa.String(length=800), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("barcode", sa.String(length=80), nullable=True),
        sa.Column("ocr_text", sa.Text(), nullable=True),
        sa.Column("extracted_brand", sa.String(length=240), nullable=True),
        sa.Column("extracted_product_name", sa.String(length=300), nullable=True),
        sa.Column("extracted_ingredient_text", sa.Text(), nullable=True),
        sa.Column("confidence_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("matched_product_code", sa.String(length=32), sa.ForeignKey("products.product_code"), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        utc_ts("created_at"),
        utc_ts("updated_at"),
    )
    op.create_table(
        "scan_candidates",
        sa.Column("candidate_code", sa.String(length=32), primary_key=True),
        sa.Column("scan_code", sa.String(length=32), sa.ForeignKey("scan_jobs.scan_code"), nullable=False),
        sa.Column("product_code", sa.String(length=32), sa.ForeignKey("products.product_code"), nullable=True),
        sa.Column("candidate_name", sa.String(length=300), nullable=False),
        sa.Column("brand_name", sa.String(length=240), nullable=True),
        sa.Column("confidence_score", sa.Float(), nullable=False),
        sa.Column("match_reasons", sa.JSON(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        utc_ts("created_at"),
    )
    op.create_table(
        "adverse_event_signals",
        sa.Column("signal_code", sa.String(length=32), primary_key=True),
        sa.Column("product_code", sa.String(length=32), sa.ForeignKey("products.product_code"), nullable=True),
        sa.Column("ingredient_code", sa.String(length=32), sa.ForeignKey("ingredients.ingredient_code"), nullable=True),
        sa.Column("source_record_code", sa.String(length=32), sa.ForeignKey("source_records.source_record_code"), nullable=False),
        sa.Column("reaction_name", sa.String(length=240), nullable=False),
        sa.Column("severity", sa.String(length=40), nullable=False),
        sa.Column("report_count", sa.Integer(), nullable=False),
        sa.Column("signal_score", sa.Float(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        utc_ts("created_at"),
    )
    op.create_table(
        "image_embeddings",
        sa.Column("embedding_code", sa.String(length=32), primary_key=True),
        sa.Column("image_code", sa.String(length=32), sa.ForeignKey("product_images.image_code"), nullable=False),
        sa.Column("product_code", sa.String(length=32), sa.ForeignKey("products.product_code"), nullable=False),
        sa.Column("model_name", sa.String(length=120), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column("vector", sa.JSON(), nullable=False),
        utc_ts("created_at"),
    )


def downgrade() -> None:
    for table in [
        "image_embeddings",
        "adverse_event_signals",
        "scan_candidates",
        "scan_jobs",
        "risk_evaluations",
        "risk_rules",
        "product_ingredients",
        "ingredient_synonyms",
        "ingredients",
        "product_images",
        "product_categories",
        "products",
        "categories",
        "brands",
        "source_records",
        "sources",
    ]:
        op.drop_table(table)
