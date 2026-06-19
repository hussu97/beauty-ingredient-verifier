"""make source record fact lookup nonunique

Revision ID: 20260619_0008
Revises: 20260619_0007
Create Date: 2026-06-19 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260619_0008"
down_revision: str | None = "20260619_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index("ix_source_record_facts_record_field_value", table_name="source_record_facts")
    op.create_index(
        "ix_source_record_facts_record_field_value",
        "source_record_facts",
        ["source_record_code", "entity_kind", "field_name", "normalized_value"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_source_record_facts_record_field_value", table_name="source_record_facts")
    op.create_index(
        "ix_source_record_facts_record_field_value",
        "source_record_facts",
        ["source_record_code", "entity_kind", "field_name", "normalized_value"],
        unique=True,
    )
