"""增加可恢复的异步审查批次表。

Revision ID: 20260726_01
Revises: 20260726_rag_metadata
"""
from alembic import op
import sqlalchemy as sa


revision = "20260726_01"
down_revision = "20260726_rag_metadata"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audit_batches",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("department", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("dimensions_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column("completed", sa.Integer(), nullable=False),
        sa.Column("failed", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_id", "idempotency_key", name="uq_audit_batches_owner_idempotency"),
    )
    op.create_index("ix_audit_batches_owner_id", "audit_batches", ["owner_id"])
    op.create_index("ix_audit_batches_department", "audit_batches", ["department"])
    op.create_index("ix_audit_batches_status", "audit_batches", ["status"])

    op.create_table(
        "audit_batch_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("batch_id", sa.Integer(), nullable=False),
        sa.Column("contract_id", sa.Integer(), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("task_id", sa.String(length=64), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["batch_id"], ["audit_batches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["contract_id"], ["contracts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("batch_id", "contract_id", name="uq_audit_batch_items_contract"),
    )
    op.create_index("ix_audit_batch_items_batch_id", "audit_batch_items", ["batch_id"])
    op.create_index("ix_audit_batch_items_contract_id", "audit_batch_items", ["contract_id"])
    op.create_index("ix_audit_batch_items_status", "audit_batch_items", ["status"])
    op.create_index("ix_audit_batch_items_task_id", "audit_batch_items", ["task_id"])


def downgrade() -> None:
    op.drop_index("ix_audit_batch_items_task_id", table_name="audit_batch_items")
    op.drop_index("ix_audit_batch_items_status", table_name="audit_batch_items")
    op.drop_index("ix_audit_batch_items_contract_id", table_name="audit_batch_items")
    op.drop_index("ix_audit_batch_items_batch_id", table_name="audit_batch_items")
    op.drop_table("audit_batch_items")
    op.drop_index("ix_audit_batches_status", table_name="audit_batches")
    op.drop_index("ix_audit_batches_department", table_name="audit_batches")
    op.drop_index("ix_audit_batches_owner_id", table_name="audit_batches")
    op.drop_table("audit_batches")
