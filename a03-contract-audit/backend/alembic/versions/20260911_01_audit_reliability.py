"""增加上传幂等与可恢复审查任务字段。

Revision ID: 20260911_01
Revises: 20260908_01
"""
from alembic import op
import sqlalchemy as sa


revision = "20260911_01"
down_revision = "20260908_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "contracts",
        sa.Column("upload_idempotency_key", sa.String(128), nullable=True),
    )
    op.add_column("contracts", sa.Column("content_sha256", sa.String(64), nullable=True))
    op.add_column(
        "contracts",
        sa.Column("audit_generation", sa.Integer(), server_default="0", nullable=False),
    )
    op.create_index(
        "uq_contracts_uploader_upload_idempotency",
        "contracts",
        ["uploaded_by", "upload_idempotency_key"],
        unique=True,
    )
    op.add_column(
        "audit_batches",
        sa.Column("request_fingerprint", sa.String(64), server_default="", nullable=False),
    )
    op.add_column(
        "audit_batch_items",
        sa.Column("error_code", sa.String(64), nullable=True),
    )
    op.add_column(
        "audit_batch_items",
        sa.Column("result_json", sa.Text(), server_default="{}", nullable=False),
    )
    op.add_column(
        "audit_batch_items",
        sa.Column("audit_generation", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "audit_batch_items",
        sa.Column("execution_token", sa.String(64), nullable=True),
    )
    op.add_column("risks", sa.Column("audit_job_id", sa.Integer(), nullable=True))
    op.create_index("ix_risks_audit_job_id", "risks", ["audit_job_id"])
    op.add_column(
        "llm_call_logs",
        sa.Column("audit_job_id", sa.Integer(), nullable=True),
    )
    op.create_index(
        "ix_llm_call_logs_audit_job_id",
        "llm_call_logs",
        ["audit_job_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_llm_call_logs_audit_job_id", table_name="llm_call_logs")
    op.drop_column("llm_call_logs", "audit_job_id")
    op.drop_column("audit_batch_items", "audit_generation")
    op.drop_column("audit_batch_items", "execution_token")
    op.drop_index("ix_risks_audit_job_id", table_name="risks")
    op.drop_column("risks", "audit_job_id")
    op.drop_column("audit_batch_items", "result_json")
    op.drop_column("audit_batch_items", "error_code")
    op.drop_column("audit_batches", "request_fingerprint")
    op.drop_index(
        "uq_contracts_uploader_upload_idempotency",
        table_name="contracts",
    )
    op.drop_column("contracts", "audit_generation")
    op.drop_column("contracts", "content_sha256")
    op.drop_column("contracts", "upload_idempotency_key")
