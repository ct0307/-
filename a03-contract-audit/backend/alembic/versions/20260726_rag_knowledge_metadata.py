"""add RAG knowledge metadata

Revision ID: 20260726_rag_metadata
Revises: 20260726_00
Create Date: 2026-07-26
"""
from alembic import op
import sqlalchemy as sa


revision = "20260726_rag_metadata"
down_revision = "20260726_00"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("knowledge_chunks", sa.Column("article_number", sa.String(64), nullable=True))
    op.add_column("knowledge_chunks", sa.Column("version", sa.String(64), nullable=True))
    op.add_column("knowledge_chunks", sa.Column("effective_date", sa.Date(), nullable=True))
    op.add_column("knowledge_chunks", sa.Column("expiry_date", sa.Date(), nullable=True))
    op.add_column(
        "knowledge_chunks",
        sa.Column("applicable_contract_types", sa.Text(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "knowledge_chunks",
        sa.Column("applicable_dimensions", sa.Text(), nullable=False, server_default="[]"),
    )
    op.add_column("knowledge_chunks", sa.Column("embedding_model", sa.String(255), nullable=True))
    op.add_column("knowledge_chunks", sa.Column("embedding_dimension", sa.Integer(), nullable=True))
    op.add_column("knowledge_chunks", sa.Column("content_hash", sa.String(64), nullable=True))


def downgrade() -> None:
    for column in (
        "content_hash",
        "embedding_dimension",
        "embedding_model",
        "applicable_dimensions",
        "applicable_contract_types",
        "expiry_date",
        "effective_date",
        "version",
        "article_number",
    ):
        op.drop_column("knowledge_chunks", column)
