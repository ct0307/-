"""新增合同交接记录，保留原有解析任务状态。"""
from alembic import op
import sqlalchemy as sa

revision = "20260929_02"
down_revision = "20260929_01"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("contract_handoffs",
        sa.Column("contract_id", sa.Integer(), sa.ForeignKey("contracts.id"), primary_key=True),
        sa.Column("state", sa.String(24), nullable=False, server_default="draft"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("submitted_by", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("assigned_to", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade():
    op.drop_table("contract_handoffs")
