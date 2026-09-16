"""增加合同解析缓存。"""

from alembic import op
import sqlalchemy as sa


revision = "20260916_02"
down_revision = "20260916_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "contract_parse_caches",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("contract_id", sa.Integer(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("parser_signature", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.LargeBinary(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["contract_id"], ["contracts.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("contract_id"),
    )
    op.create_index(
        "ix_contract_parse_caches_contract_id",
        "contract_parse_caches",
        ["contract_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_contract_parse_caches_contract_id",
        table_name="contract_parse_caches",
    )
    op.drop_table("contract_parse_caches")
