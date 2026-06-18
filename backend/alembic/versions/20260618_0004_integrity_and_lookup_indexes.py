"""integrity constraints and lookup indexes

Revision ID: 20260618_0004
Revises: 20260618_0003
Create Date: 2026-06-18 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260618_0004"
down_revision: str | None = "20260618_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _index_names(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {row["name"] for row in inspector.get_indexes(table_name)}


def _create_index_once(name: str, table_name: str, columns: list[str], *, unique: bool = False) -> None:
    if name not in _index_names(table_name):
        op.create_index(name, table_name, columns, unique=unique)


def _drop_index_once(name: str, table_name: str) -> None:
    if name in _index_names(table_name):
        op.drop_index(name, table_name=table_name)


def _dedupe_product_source_links() -> None:
    bind = op.get_bind()
    groups = bind.execute(
        sa.text(
            """
            select source_code, external_id
            from product_source_links
            group by source_code, external_id
            having count(*) > 1
            """
        )
    ).fetchall()
    for source_code, external_id in groups:
        links = bind.execute(
            sa.text(
                """
                select product_source_link_code
                from product_source_links
                where source_code = :source_code and external_id = :external_id
                order by active desc, match_confidence desc, updated_at desc, created_at asc
                """
            ),
            {"source_code": source_code, "external_id": external_id},
        ).fetchall()
        keep = links[0][0]
        stale = [row[0] for row in links[1:]]
        if stale:
            bind.execute(
                sa.text(
                    """
                    delete from product_source_links
                    where product_source_link_code in :stale
                    """
                ).bindparams(sa.bindparam("stale", expanding=True)),
                {"stale": stale},
            )
            bind.execute(
                sa.text(
                    """
                    update product_source_links
                    set active = 1
                    where product_source_link_code = :keep
                    """
                ),
                {"keep": keep},
            )


def upgrade() -> None:
    _dedupe_product_source_links()

    # Replace the older source-record natural key with one that includes the
    # source entity type, so product and ingredient records cannot collide.
    _drop_index_once("ix_source_records_source_external", "source_records")
    _create_index_once("ix_source_records_source_external", "source_records", ["source_code", "external_id"])
    _create_index_once(
        "ix_source_records_source_type_external",
        "source_records",
        ["source_code", "record_type", "external_id"],
        unique=True,
    )

    _create_index_once("ix_products_brand", "products", ["brand_code"])
    _create_index_once("ix_product_categories_category", "product_categories", ["category_code"])
    _create_index_once("ix_product_images_product", "product_images", ["product_code"])
    _create_index_once(
        "ix_product_ingredients_product_ingredient",
        "product_ingredients",
        ["product_code", "ingredient_code"],
        unique=True,
    )
    _create_index_once(
        "ix_product_source_links_source_external",
        "product_source_links",
        ["source_code", "external_id"],
        unique=True,
    )
    _create_index_once("ix_image_embeddings_model_dimensions", "image_embeddings", ["model_name", "dimensions"])
    _create_index_once("ix_image_embeddings_product_model", "image_embeddings", ["product_code", "model_name"])


def downgrade() -> None:
    _drop_index_once("ix_image_embeddings_product_model", "image_embeddings")
    _drop_index_once("ix_image_embeddings_model_dimensions", "image_embeddings")
    _drop_index_once("ix_product_source_links_source_external", "product_source_links")
    _drop_index_once("ix_product_ingredients_product_ingredient", "product_ingredients")
    _drop_index_once("ix_product_images_product", "product_images")
    _drop_index_once("ix_product_categories_category", "product_categories")
    _drop_index_once("ix_products_brand", "products")
    _drop_index_once("ix_source_records_source_type_external", "source_records")
    _drop_index_once("ix_source_records_source_external", "source_records")
    op.create_index("ix_source_records_source_external", "source_records", ["source_code", "external_id"], unique=True)
