"""增加 OCR 解析质量字段。

Revision ID: 20260726_02
Revises: 20260726_01
"""
from alembic import op
import sqlalchemy as sa


revision = "20260726_02"
down_revision = "20260726_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "contracts",
        sa.Column(
            "parse_source",
            sa.String(length=16),
            server_default="native",
            nullable=False,
        ),
    )
    op.add_column(
        "contracts",
        sa.Column("ocr_confidence", sa.Float(), nullable=True),
    )
    op.add_column(
        "contracts",
        sa.Column(
            "requires_review",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )
    op.add_column(
        "contracts",
        sa.Column("review_reason", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("contracts", "review_reason")
    op.drop_column("contracts", "requires_review")
    op.drop_column("contracts", "ocr_confidence")
    op.drop_column("contracts", "parse_source")
