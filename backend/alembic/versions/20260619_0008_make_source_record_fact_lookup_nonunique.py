"""make source record fact lookup nonunique

Revision ID: 20260619_0008
Revises: 20260619_0007
Create Date: 2026-06-19 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260619_0008"
down_revision: str | None = "20260619_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _index_names(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {row["name"] for row in inspector.get_indexes(table_name)}


def _drop_index_once(name: str, table_name: str) -> None:
    if name in _index_names(table_name):
        op.drop_index(name, table_name=table_name)


def _create_index_once(name: str, table_name: str, columns: list[str], *, unique: bool) -> None:
    if name not in _index_names(table_name):
        op.create_index(name, table_name, columns, unique=unique)


def upgrade() -> None:
    _drop_index_once("ix_source_record_facts_record_field_value", "source_record_facts")
    _create_index_once(
        "ix_source_record_facts_record_field_value",
        "source_record_facts",
        ["source_record_code", "entity_kind", "field_name", "normalized_value"],
        unique=False,
    )


def downgrade() -> None:
    _drop_index_once("ix_source_record_facts_record_field_value", "source_record_facts")
    _create_index_once(
        "ix_source_record_facts_record_field_value",
        "source_record_facts",
        ["source_record_code", "entity_kind", "field_name", "normalized_value"],
        unique=True,
    )
