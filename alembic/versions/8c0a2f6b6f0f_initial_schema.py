"""initial schema

Revision ID: 8c0a2f6b6f0f
Revises:
Create Date: 2026-04-09 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "8c0a2f6b6f0f"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("extension", sa.String(length=16), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("indexed_chunks", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_documents_filename"), "documents", ["filename"], unique=True)

    op.create_table(
        "ingestion_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("files_count", sa.Integer(), nullable=False),
        sa.Column("chunks_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error_message", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("ingestion_runs")
    op.drop_index(op.f("ix_documents_filename"), table_name="documents")
    op.drop_table("documents")
