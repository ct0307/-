"""增加风险证据状态与原文校验字段。

Revision ID: 20260911_05
Revises: 20260911_02
"""
from alembic import op
import sqlalchemy as sa


revision = "20260911_05"
down_revision = "20260911_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "risks", sa.Column("risk_reason", sa.Text(), server_default="", nullable=False)
    )
    op.add_column(
        "risks",
        sa.Column(
            "evidence_status",
            sa.String(24),
            server_default="unsupported",
            nullable=False,
        ),
    )
    op.add_column(
        "risks", sa.Column("original_text_verified", sa.Boolean(), nullable=True)
    )
    op.add_column(
        "risks",
        sa.Column(
            "requires_manual_review", sa.Boolean(), server_default=sa.true(), nullable=False
        ),
    )


def downgrade() -> None:
    op.drop_column("risks", "requires_manual_review")
    op.drop_column("risks", "original_text_verified")
    op.drop_column("risks", "evidence_status")
    op.drop_column("risks", "risk_reason")
