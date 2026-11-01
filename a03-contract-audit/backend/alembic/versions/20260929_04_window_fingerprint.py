"""使窗口检查点绑定运行版本指纹。"""
from alembic import op
import sqlalchemy as sa

revision = '20260929_04'
down_revision = '20260929_03'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('audit_window_runs') as batch:
        batch.add_column(sa.Column('run_fingerprint', sa.String(64), nullable=False, server_default=''))
        batch.drop_constraint('uq_audit_window_runs_identity', type_='unique')
        batch.create_unique_constraint('uq_audit_window_runs_identity', [
            'audit_job_id', 'audit_generation', 'agent', 'dimensions_hash',
            'window_id', 'protocol_version', 'run_fingerprint'])


def downgrade():
    # 多个运行版本可能共享旧身份；存在重复时明确失败，不静默丢弃历史。
    with op.batch_alter_table('audit_window_runs') as batch:
        batch.drop_constraint('uq_audit_window_runs_identity', type_='unique')
        batch.create_unique_constraint('uq_audit_window_runs_identity', [
            'audit_job_id', 'audit_generation', 'agent', 'dimensions_hash',
            'window_id', 'protocol_version'])
        batch.drop_column('run_fingerprint')
