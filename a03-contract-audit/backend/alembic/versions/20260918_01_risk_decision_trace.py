"""持久化风险证据适用性、规则执行和统一决策轨迹。"""

from alembic import op
import sqlalchemy as sa


revision = "20260918_01"
down_revision = "20260917_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = [
        ("support_validation_failed_stage", sa.String(32), "none"),
        ("support_validation_reason_code", sa.String(64), ""),
        ("applicability_status", sa.String(24), "unresolved"),
        ("applicability_reason_codes_json", sa.Text(), "[]"),
        ("rule_executions_json", sa.Text(), "[]"),
        ("decision_trace_json", sa.Text(), "{}"),
    ]
    for name, type_, default in columns:
        op.add_column(
            "risks",
            sa.Column(name, type_, server_default=default, nullable=False),
        )


def downgrade() -> None:
    for name in (
        "decision_trace_json",
        "rule_executions_json",
        "applicability_reason_codes_json",
        "applicability_status",
        "support_validation_reason_code",
        "support_validation_failed_stage",
    ):
        op.drop_column("risks", name)
