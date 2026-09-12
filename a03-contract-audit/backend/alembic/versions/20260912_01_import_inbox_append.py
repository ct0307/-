"""增加收件箱追加请求幂等记录。"""

from alembic import op
import sqlalchemy as sa


revision = "20260912_01"
down_revision = "20260911_07"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "import_batches",
        sa.Column(
            "request_fingerprint",
            sa.String(64),
            server_default="",
            nullable=False,
        ),
    )
    op.add_column(
        "import_batches",
        sa.Column("department", sa.String(64), server_default="", nullable=False),
    )
    op.execute(
        """
        UPDATE import_batches
        SET department = COALESCE((
            SELECT contracts.department
            FROM import_batch_items
            JOIN contracts ON contracts.id = import_batch_items.contract_id
            WHERE import_batch_items.batch_id = import_batches.id
            ORDER BY import_batch_items.id
            LIMIT 1
        ), '')
        """
    )
    op.create_table(
        "import_append_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "batch_id",
            sa.Integer(),
            sa.ForeignKey("import_batches.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "batch_id",
            "idempotency_key",
            name="uq_import_append_batch_key",
        ),
    )
    op.create_index(
        "ix_import_append_requests_batch_id",
        "import_append_requests",
        ["batch_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_import_append_requests_batch_id",
        table_name="import_append_requests",
    )
    op.drop_table("import_append_requests")
    op.drop_column("import_batches", "department")
    op.drop_column("import_batches", "request_fingerprint")
