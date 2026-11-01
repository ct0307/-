"""保存审查工作流及人工终审，不改变机器审查状态。"""
from alembic import op
import sqlalchemy as sa

revision = '20260929_03'
down_revision = '20260929_02'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('audit_workflows',
        sa.Column('id',sa.Integer(),primary_key=True),
        sa.Column('contract_id',sa.Integer(),sa.ForeignKey('contracts.id'),nullable=False),
        sa.Column('audit_generation',sa.Integer(),nullable=False),
        sa.Column('audit_job_id',sa.Integer(),nullable=True),
        sa.Column('snapshot_json',sa.Text(),nullable=False,server_default='{}'),
        sa.Column('version',sa.Integer(),nullable=False,server_default='0'),
        sa.Column('review_json',sa.Text(),nullable=False,server_default='{}'),
        sa.Column('published_fingerprint',sa.String(64),nullable=False,server_default=''),
        sa.Column('reviewed_by',sa.Integer(),sa.ForeignKey('users.id'),nullable=True),
        sa.Column('reviewed_at',sa.DateTime(timezone=True),nullable=True),
        sa.UniqueConstraint('contract_id','audit_generation',name='uq_workflow_generation'))
    op.create_index('ix_audit_workflows_contract_id','audit_workflows',['contract_id'])


def downgrade():
    op.drop_table('audit_workflows')
