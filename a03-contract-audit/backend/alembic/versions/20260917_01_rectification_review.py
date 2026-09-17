"""增加整改提交与复核闭环字段。"""

from alembic import op
import sqlalchemy as sa


revision = "20260917_01"
down_revision = "20260916_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "rectifications",
        sa.Column("resolution", sa.Text(), server_default="", nullable=False),
    )
    op.add_column(
        "rectifications",
        sa.Column("review_comment", sa.Text(), server_default="", nullable=False),
    )
    op.add_column("rectifications", sa.Column("submitted_at", sa.DateTime(timezone=True)))
    op.add_column("rectifications", sa.Column("closed_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.drop_column("rectifications", "closed_at")
    op.drop_column("rectifications", "submitted_at")
    op.drop_column("rectifications", "review_comment")
    op.drop_column("rectifications", "resolution")
