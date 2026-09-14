"""持久化批次审查项的真实进度。"""
from alembic import op
import sqlalchemy as sa


revision = "20260914_01"
down_revision = "20260913_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "audit_batch_items",
        sa.Column("progress", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "audit_batch_items",
        sa.Column(
            "progress_stage",
            sa.String(24),
            server_default="queued",
            nullable=False,
        ),
    )
    op.execute(
        """
        UPDATE audit_batch_items
        SET progress = CASE status
            WHEN 'parsing' THEN 5
            WHEN 'reviewing' THEN 15
            WHEN 'validating' THEN 90
            WHEN 'done' THEN 100
            WHEN 'review_required' THEN 100
            ELSE 0
        END,
        progress_stage = CASE status
            WHEN 'parsing' THEN 'parsing'
            WHEN 'reviewing' THEN 'reviewing'
            WHEN 'validating' THEN 'persisting'
            WHEN 'done' THEN 'completed'
            WHEN 'review_required' THEN 'completed'
            WHEN 'failed' THEN 'failed'
            ELSE 'queued'
        END
        """
    )


def downgrade() -> None:
    op.drop_column("audit_batch_items", "progress_stage")
    op.drop_column("audit_batch_items", "progress")
