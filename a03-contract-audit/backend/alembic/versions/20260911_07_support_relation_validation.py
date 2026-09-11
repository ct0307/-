"""增加风险依据支持关系校验结果。"""

from alembic import op
import sqlalchemy as sa


revision = "20260911_07"
down_revision = "20260911_06"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "risks",
        sa.Column(
            "support_relation_status",
            sa.String(16),
            server_default="unclear",
            nullable=False,
        ),
    )
    op.add_column(
        "risks",
        sa.Column(
            "support_validation_reason",
            sa.Text(),
            server_default="",
            nullable=False,
        ),
    )
    op.add_column(
        "risks",
        sa.Column(
            "support_validator_version",
            sa.String(32),
            server_default="unvalidated",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("risks", "support_validator_version")
    op.drop_column("risks", "support_validation_reason")
    op.drop_column("risks", "support_relation_status")
