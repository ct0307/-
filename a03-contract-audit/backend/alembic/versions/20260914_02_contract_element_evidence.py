"""持久化合同六要素原文证据。"""

from alembic import op
import sqlalchemy as sa


revision = "20260914_02"
down_revision = "20260914_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "contracts",
        sa.Column(
            "element_evidence_json",
            sa.Text(),
            server_default="{}",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("contracts", "element_evidence_json")
