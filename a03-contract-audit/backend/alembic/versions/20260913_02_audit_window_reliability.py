"""持久化窗口检查点、调用观测与二次复核状态。"""
from alembic import op
import sqlalchemy as sa


revision = "20260913_02"
down_revision = "20260913_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audit_window_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("contract_id", sa.Integer(), sa.ForeignKey("contracts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("audit_job_id", sa.Integer(), nullable=False),
        sa.Column("audit_generation", sa.Integer(), nullable=False),
        sa.Column("agent", sa.String(16), nullable=False),
        sa.Column("dimensions_hash", sa.String(64), nullable=False),
        sa.Column("window_id", sa.String(64), nullable=False),
        sa.Column("parent_window_id", sa.String(64), nullable=True),
        sa.Column("depth", sa.Integer(), server_default="0", nullable=False),
        sa.Column("protocol_version", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("result_json", sa.Text(), server_default="{}", nullable=False),
        sa.Column("issues_json", sa.Text(), server_default="[]", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint(
            "audit_job_id", "audit_generation", "agent", "dimensions_hash", "window_id", "protocol_version",
            name="uq_audit_window_runs_identity",
        ),
    )
    op.create_index("ix_audit_window_runs_contract_id", "audit_window_runs", ["contract_id"])
    op.create_index("ix_audit_window_runs_audit_job_id", "audit_window_runs", ["audit_job_id"])
    with op.batch_alter_table("llm_call_logs") as batch:
        batch.add_column(sa.Column("window_id", sa.String(64), nullable=True))
        batch.add_column(sa.Column("dimension", sa.String(64), server_default="all", nullable=False))
        batch.add_column(sa.Column("attempt", sa.Integer(), server_default="1", nullable=False))
        batch.add_column(sa.Column("validation_status", sa.String(24), server_default="unknown", nullable=False))
        batch.add_column(sa.Column("error_code", sa.String(64), nullable=True))
    with op.batch_alter_table("risks") as batch:
        batch.add_column(sa.Column("secondary_review_status", sa.String(24), server_default="not_required", nullable=False))
        batch.add_column(sa.Column("secondary_review_reason", sa.Text(), server_default="", nullable=False))
    op.execute("UPDATE contracts SET status = 'reviewing' WHERE status = 'auditing'")
    op.execute("UPDATE audit_batch_items SET status = 'reviewing' WHERE status = 'auditing'")


def downgrade() -> None:
    # 旧代码只认识 auditing，且没有 review_required；后者已有可读结果，
    # 因此映射为 done，并保留合同复核标记及任务 result_json，而不是伪装成失败。
    op.execute(
        "UPDATE audit_batch_items SET status = 'auditing' "
        "WHERE status IN ('reviewing', 'validating')"
    )
    op.execute("UPDATE audit_batch_items SET status = 'done' WHERE status = 'review_required'")
    op.execute(
        "UPDATE contracts SET status = 'auditing' "
        "WHERE status IN ('reviewing', 'validating')"
    )
    op.execute("UPDATE contracts SET status = 'done' WHERE status = 'review_required'")
    op.execute("UPDATE audit_batches SET status = 'done' WHERE status = 'review_required'")
    with op.batch_alter_table("risks") as batch:
        batch.drop_column("secondary_review_reason")
        batch.drop_column("secondary_review_status")
    with op.batch_alter_table("llm_call_logs") as batch:
        batch.drop_column("error_code")
        batch.drop_column("validation_status")
        batch.drop_column("attempt")
        batch.drop_column("dimension")
        batch.drop_column("window_id")
    op.drop_index("ix_audit_window_runs_audit_job_id", table_name="audit_window_runs")
    op.drop_index("ix_audit_window_runs_contract_id", table_name="audit_window_runs")
    op.drop_table("audit_window_runs")
