"""将知识作用域与来源审批状态分离，历史普通上传保持未核验。"""
from alembic import op
import sqlalchemy as sa

revision = "20260929_01"
down_revision = "20260918_01"
branch_labels = None
depends_on = None


def upgrade():
    for column in (
        sa.Column("trust_status", sa.String(24), nullable=False, server_default="unverified"),
        sa.Column("approved_by", sa.Integer(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approval_version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("approved_content_hash", sa.String(64), nullable=False, server_default=""),
    ):
        op.add_column("knowledge_chunks", column)


def downgrade():
    for name in ("approved_content_hash", "approval_version", "approved_at", "approved_by", "trust_status"):
        op.drop_column("knowledge_chunks", name)
