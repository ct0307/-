"""Add explicit trust scope to knowledge chunks.

Revision ID: 20260731_01
Revises: 20260726_02
"""

from alembic import op
import sqlalchemy as sa


revision = "20260731_01"
down_revision = "20260726_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "knowledge_chunks",
        sa.Column(
            "scope_mode",
            sa.String(length=16),
            server_default="unclassified",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("knowledge_chunks", "scope_mode")
