"""widen ingredient name columns

Revision ID: 20260619_0006
Revises: 20260618_0005
Create Date: 2026-06-19 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260619_0006"
down_revision: str | None = "20260618_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        return

    op.alter_column(
        "ingredients",
        "canonical_name",
        existing_type=sa.String(length=260),
        type_=sa.Text(),
        existing_nullable=False,
    )
    op.alter_column(
        "ingredients",
        "normalized_name",
        existing_type=sa.String(length=280),
        type_=sa.Text(),
        existing_nullable=False,
    )
    op.alter_column(
        "ingredients",
        "inci_name",
        existing_type=sa.String(length=260),
        type_=sa.Text(),
        existing_nullable=True,
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        return

    op.alter_column(
        "ingredients",
        "inci_name",
        existing_type=sa.Text(),
        type_=sa.String(length=260),
        existing_nullable=True,
    )
    op.alter_column(
        "ingredients",
        "normalized_name",
        existing_type=sa.Text(),
        type_=sa.String(length=280),
        existing_nullable=False,
    )
    op.alter_column(
        "ingredients",
        "canonical_name",
        existing_type=sa.Text(),
        type_=sa.String(length=260),
        existing_nullable=False,
    )
