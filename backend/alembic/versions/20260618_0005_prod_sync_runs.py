"""production sync runs and pgvector index

Revision ID: 20260618_0005
Revises: 20260618_0004
Create Date: 2026-06-18 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260618_0005"
down_revision: str | None = "20260618_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sync_runs",
        sa.Column("sync_run_code", sa.String(length=32), nullable=False),
        sa.Column("mode", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("source_database", sa.String(length=1000), nullable=False),
        sa.Column("source_fingerprint", sa.String(length=80), nullable=False),
        sa.Column("tables", sa.JSON(), nullable=False),
        sa.Column("row_counts", sa.JSON(), nullable=False),
        sa.Column("failure_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("sync_run_code"),
    )
    op.create_index("ix_sync_runs_source_fingerprint", "sync_runs", ["source_fingerprint"])

    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS image_embedding_vectors (
            embedding_code VARCHAR(32) PRIMARY KEY
                REFERENCES image_embeddings(embedding_code) ON DELETE CASCADE,
            image_code VARCHAR(32) NOT NULL,
            product_code VARCHAR(32) NOT NULL,
            model_name VARCHAR(120) NOT NULL,
            dimensions INTEGER NOT NULL,
            embedding vector(512) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_image_embedding_vectors_product_model
        ON image_embedding_vectors (product_code, model_name)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_image_embedding_vectors_model_dims
        ON image_embedding_vectors (model_name, dimensions)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_image_embedding_vectors_embedding_hnsw
        ON image_embedding_vectors USING hnsw (embedding vector_cosine_ops)
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_image_embedding_vectors_embedding_hnsw")
        op.execute("DROP INDEX IF EXISTS ix_image_embedding_vectors_model_dims")
        op.execute("DROP INDEX IF EXISTS ix_image_embedding_vectors_product_model")
        op.execute("DROP TABLE IF EXISTS image_embedding_vectors")

    op.drop_index("ix_sync_runs_source_fingerprint", table_name="sync_runs")
    op.drop_table("sync_runs")
