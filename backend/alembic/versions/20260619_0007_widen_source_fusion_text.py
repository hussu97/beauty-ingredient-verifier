"""widen source fusion text fields

Revision ID: 20260619_0007
Revises: 20260619_0006
Create Date: 2026-06-19 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260619_0007"
down_revision: str | None = "20260619_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        return

    op.alter_column(
        "product_ingredients",
        "raw_name",
        existing_type=sa.String(length=260),
        type_=sa.Text(),
        existing_nullable=False,
    )
    op.alter_column(
        "ingredient_source_links",
        "external_id",
        existing_type=sa.String(length=300),
        type_=sa.Text(),
        existing_nullable=False,
    )
    op.alter_column(
        "canonical_terms",
        "slug",
        existing_type=sa.String(length=220),
        type_=sa.Text(),
        existing_nullable=False,
    )
    op.alter_column(
        "canonical_terms",
        "label",
        existing_type=sa.String(length=240),
        type_=sa.Text(),
        existing_nullable=False,
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        return

    op.alter_column(
        "canonical_terms",
        "label",
        existing_type=sa.Text(),
        type_=sa.String(length=240),
        existing_nullable=False,
    )
    op.alter_column(
        "canonical_terms",
        "slug",
        existing_type=sa.Text(),
        type_=sa.String(length=220),
        existing_nullable=False,
    )
    op.alter_column(
        "ingredient_source_links",
        "external_id",
        existing_type=sa.Text(),
        type_=sa.String(length=300),
        existing_nullable=False,
    )
    op.alter_column(
        "product_ingredients",
        "raw_name",
        existing_type=sa.Text(),
        type_=sa.String(length=260),
        existing_nullable=False,
    )
