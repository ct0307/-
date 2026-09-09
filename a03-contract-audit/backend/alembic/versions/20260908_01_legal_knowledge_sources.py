"""增加权威法源、完整法条和检索子切片关联。

Revision ID: 20260908_01
Revises: 20260731_01
"""
from alembic import op
import sqlalchemy as sa


revision = "20260908_01"
down_revision = "20260731_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "legal_sources",
        sa.Column("source_id", sa.String(64), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("issuing_authority", sa.String(255), nullable=False),
        sa.Column("official_url", sa.String(1024), nullable=False),
        sa.Column("publication_date", sa.Date(), nullable=False),
        sa.Column("effective_date", sa.Date(), nullable=False),
        sa.Column("version_status", sa.String(32), nullable=False),
        sa.Column("retrieved_at", sa.Date(), nullable=False),
        sa.Column("file_sha256", sa.String(64), nullable=False),
        sa.PrimaryKeyConstraint("source_id"),
    )
    op.create_table(
        "legal_articles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.String(64), nullable=False),
        sa.Column("article_number", sa.String(64), nullable=False),
        sa.Column("article_sort", sa.Integer(), nullable=False),
        sa.Column("chapter_title", sa.String(255), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.ForeignKeyConstraint(["source_id"], ["legal_sources.source_id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_id", "article_number", name="uq_legal_article_source_number"
        ),
    )
    op.create_index("ix_legal_articles_source_id", "legal_articles", ["source_id"])

    with op.batch_alter_table("knowledge_chunks") as batch_op:
        batch_op.add_column(sa.Column("legal_article_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("chunk_index", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("chunk_count", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("chunk_schema_version", sa.String(32), nullable=True))
        batch_op.add_column(sa.Column("retrieval_text", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("embedding_signature", sa.String(64), nullable=True))
        batch_op.create_foreign_key(
            "fk_knowledge_chunks_legal_article_id",
            "legal_articles",
            ["legal_article_id"],
            ["id"],
        )
        batch_op.create_index("ix_knowledge_chunks_legal_article_id", ["legal_article_id"])


def downgrade() -> None:
    with op.batch_alter_table("knowledge_chunks") as batch_op:
        batch_op.drop_index("ix_knowledge_chunks_legal_article_id")
        batch_op.drop_constraint("fk_knowledge_chunks_legal_article_id", type_="foreignkey")
        for column in (
            "embedding_signature",
            "retrieval_text",
            "chunk_schema_version",
            "chunk_count",
            "chunk_index",
            "legal_article_id",
        ):
            batch_op.drop_column(column)
    op.drop_index("ix_legal_articles_source_id", table_name="legal_articles")
    op.drop_table("legal_articles")
    op.drop_table("legal_sources")
