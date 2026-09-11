"""记录模型输出结束原因。

Revision ID: 20260911_06
Revises: 20260911_05
"""
from alembic import op
import sqlalchemy as sa


revision = "20260911_06"
down_revision = "20260911_05"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("llm_call_logs", sa.Column("finish_reason", sa.String(32), nullable=True))


def downgrade() -> None:
    op.drop_column("llm_call_logs", "finish_reason")
