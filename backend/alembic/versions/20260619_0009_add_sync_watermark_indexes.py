"""Add sync watermark indexes.

Revision ID: 20260619_0009
Revises: 20260619_0008
Create Date: 2026-06-19
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260619_0009"
down_revision = "20260619_0008"
branch_labels = None
depends_on = None


INDEXES = (
    ("ix_sources_updated_at", "sources", ("updated_at",)),
    ("ix_source_records_created_at", "source_records", ("created_at",)),
    ("ix_source_record_facts_updated_at", "source_record_facts", ("updated_at",)),
    ("ix_product_source_links_updated_at", "product_source_links", ("updated_at",)),
    ("ix_ingredient_source_links_updated_at", "ingredient_source_links", ("updated_at",)),
    ("ix_canonical_terms_updated_at", "canonical_terms", ("updated_at",)),
    ("ix_term_aliases_created_at", "term_aliases", ("created_at",)),
    ("ix_product_term_links_created_at", "product_term_links", ("created_at",)),
    ("ix_ingredient_term_links_created_at", "ingredient_term_links", ("created_at",)),
    ("ix_brands_updated_at", "brands", ("updated_at",)),
    ("ix_categories_updated_at", "categories", ("updated_at",)),
    ("ix_products_updated_at", "products", ("updated_at",)),
    ("ix_product_images_updated_at", "product_images", ("updated_at",)),
    ("ix_ingredients_updated_at", "ingredients", ("updated_at",)),
    ("ix_ingredient_synonyms_created_at", "ingredient_synonyms", ("created_at",)),
    ("ix_product_ingredients_created_at", "product_ingredients", ("created_at",)),
    ("ix_risk_rules_updated_at", "risk_rules", ("updated_at",)),
    ("ix_adverse_event_signals_created_at", "adverse_event_signals", ("created_at",)),
    ("ix_image_embeddings_updated_at", "image_embeddings", ("updated_at",)),
)


def _index_names(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {row["name"] for row in inspector.get_indexes(table_name)}


def _create_index_once(name: str, table_name: str, columns: list[str]) -> None:
    if name not in _index_names(table_name):
        op.create_index(name, table_name, columns, unique=False)


def _drop_index_once(name: str, table_name: str) -> None:
    if name in _index_names(table_name):
        op.drop_index(name, table_name=table_name)


def _column_names(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {row["name"] for row in inspector.get_columns(table_name)}


def upgrade() -> None:
    if "updated_at" not in _column_names("image_embeddings"):
        op.add_column("image_embeddings", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))
        op.execute("UPDATE image_embeddings SET updated_at = created_at WHERE updated_at IS NULL")

    for index_name, table_name, columns in INDEXES:
        _create_index_once(index_name, table_name, list(columns))


def downgrade() -> None:
    for index_name, table_name, _columns in reversed(INDEXES):
        _drop_index_once(index_name, table_name)

    if "updated_at" in _column_names("image_embeddings"):
        op.drop_column("image_embeddings", "updated_at")
