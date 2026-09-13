"""增加智能合同收件箱数据结构。

Revision ID: 20260911_02
Revises: 20260911_01
"""

from alembic import op
import sqlalchemy as sa


revision = "20260911_02"
down_revision = "20260911_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("authorized_departments_json", sa.Text(), server_default="[]", nullable=False))
    op.add_column("contracts", sa.Column("suggested_type", sa.String(64), server_default="", nullable=False))
    op.add_column("contracts", sa.Column("type_confidence", sa.Float(), nullable=True))
    op.add_column("contracts", sa.Column("type_evidence_json", sa.Text(), server_default="[]", nullable=False))
    op.add_column("contracts", sa.Column("type_confirmed_by", sa.Integer(), nullable=True))
    op.add_column("contracts", sa.Column("type_confirmed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("contracts", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("contracts", sa.Column("deleted_by", sa.Integer(), nullable=True))
    op.create_index("ix_contracts_deleted_at", "contracts", ["deleted_at"])
    with op.batch_alter_table("contracts") as batch_op:
        batch_op.create_foreign_key(
            "fk_contracts_type_confirmed_by_users",
            "users",
            ["type_confirmed_by"],
            ["id"],
        )
        batch_op.create_foreign_key(
            "fk_contracts_deleted_by_users",
            "users",
            ["deleted_by"],
            ["id"],
        )
    op.create_table(
        "import_batches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False, server_default=""),
        sa.Column("status", sa.String(24), nullable=False, server_default="processing"),
        sa.Column("total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ready", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("owner_id", "idempotency_key", name="uq_import_batches_owner_key"),
    )
    op.create_index("ix_import_batches_owner_id", "import_batches", ["owner_id"])
    op.create_index("ix_import_batches_status", "import_batches", ["status"])
    op.create_table(
        "import_batch_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("batch_id", sa.Integer(), sa.ForeignKey("import_batches.id", ondelete="CASCADE"), nullable=False),
        sa.Column("contract_id", sa.Integer(), sa.ForeignKey("contracts.id"), nullable=True),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_import_batch_items_batch_id", "import_batch_items", ["batch_id"])
    op.create_index("ix_import_batch_items_contract_id", "import_batch_items", ["contract_id"])
    op.create_index("ix_import_batch_items_status", "import_batch_items", ["status"])
    with op.batch_alter_table("audit_batch_items") as batch_op:
        batch_op.add_column(sa.Column("import_item_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_audit_batch_items_import_item_id",
            "import_batch_items",
            ["import_item_id"],
            ["id"],
        )
        batch_op.create_index("ix_audit_batch_items_import_item_id", ["import_item_id"])
    op.execute("UPDATE contracts SET suggested_type = contract_type, type_confirmed_at = created_at WHERE contract_type IS NOT NULL AND contract_type <> ''")


def downgrade() -> None:
    with op.batch_alter_table("audit_batch_items") as batch_op:
        batch_op.drop_index("ix_audit_batch_items_import_item_id")
        batch_op.drop_constraint("fk_audit_batch_items_import_item_id", type_="foreignkey")
        batch_op.drop_column("import_item_id")
    op.drop_index("ix_import_batch_items_status", table_name="import_batch_items")
    op.drop_index("ix_import_batch_items_contract_id", table_name="import_batch_items")
    op.drop_index("ix_import_batch_items_batch_id", table_name="import_batch_items")
    op.drop_table("import_batch_items")
    op.drop_index("ix_import_batches_status", table_name="import_batches")
    op.drop_index("ix_import_batches_owner_id", table_name="import_batches")
    op.drop_table("import_batches")
    with op.batch_alter_table("contracts") as batch_op:
        batch_op.drop_constraint("fk_contracts_deleted_by_users", type_="foreignkey")
        batch_op.drop_constraint("fk_contracts_type_confirmed_by_users", type_="foreignkey")
    op.drop_index("ix_contracts_deleted_at", table_name="contracts")
    for column in ("deleted_by", "deleted_at", "type_confirmed_at", "type_confirmed_by", "type_evidence_json", "type_confidence", "suggested_type"):
        op.drop_column("contracts", column)
    op.drop_column("users", "authorized_departments_json")
