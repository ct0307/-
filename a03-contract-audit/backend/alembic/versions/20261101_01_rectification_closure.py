"""整改责任、证据快照、独立验收、事件及乐观锁。"""
from alembic import op
import sqlalchemy as sa

revision = "20261101_01"
down_revision = "20260929_04"
branch_labels = None
depends_on = None


def upgrade():
    # SQLite 需复制表才能新增外键；PostgreSQL 的同一批操作生成原生 ALTER。
    with op.batch_alter_table("rectifications") as batch:
        for name in ("acceptance_criteria", "handling_method", "after_text", "acceptance_reason", "residual_risk", "escalation_reason"):
            kind = sa.String(16) if name == "handling_method" else sa.Text()
            batch.add_column(sa.Column(name, kind, nullable=False, server_default=""))
        batch.add_column(sa.Column("contract_stage", sa.String(16), nullable=False, server_default="unknown"))
        for name in ("collaborators_json", "evidence_json"):
            batch.add_column(sa.Column(name, sa.Text(), nullable=False, server_default="[]"))
        for name in ("submitted_by", "reviewed_by", "escalated_by"):
            batch.add_column(sa.Column(name, sa.Integer(), nullable=True))
            batch.create_foreign_key(f"fk_rectifications_{name}_users", "users", [name], ["id"])
        for name in ("reviewed_at", "accepted_at", "escalated_at"):
            batch.add_column(sa.Column(name, sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("version", sa.Integer(), nullable=False, server_default="1"))
    op.create_table("rectification_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("rectification_id", sa.Integer(), sa.ForeignKey("rectifications.id"), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("actor", sa.String(64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("from_status", sa.String(16), nullable=True),
        sa.Column("to_status", sa.String(16), nullable=False),
        sa.Column("snapshot_json", sa.Text(), nullable=False))
    op.create_index("ix_rectification_events_rectification_id", "rectification_events", ["rectification_id"])


def downgrade():
    # 只允许未产生整改数据的环境回退。检查必须发生在任何DDL之前。
    if op.get_context().as_sql:
        raise RuntimeError("整改闭环回退必须在线检查数据，不能生成盲目删除的离线SQL")
    conn = op.get_bind()
    # 检查与DDL必须共享写锁，阻止在“空表检查后”插入新审计证据。
    # PostgreSQL锁由Alembic外层事务持有至提交，不在迁移函数内提交。
    if conn.dialect.name == "postgresql":
        if not conn.in_transaction():
            raise RuntimeError("PostgreSQL整改回退必须在迁移事务内执行")
        conn.execute(sa.text("LOCK TABLE rectifications, rectification_events IN ACCESS EXCLUSIVE MODE"))
    elif conn.dialect.name == "sqlite":
        # 零行UPDATE不会修改数据，但会在legacy模式开启实际写事务、取得reserved锁。
        # 使用已有事务避免BEGIN IMMEDIATE与调用方的事务嵌套冲突。
        conn.execute(sa.text("UPDATE rectifications SET id = id WHERE 1 = 0"))
        if not conn.connection.driver_connection.in_transaction:
            raise RuntimeError("SQLite整改回退必须持有实际写事务，拒绝自动提交模式下的DDL")
    else:
        raise RuntimeError("当前数据库未实现安全整改回退锁，拒绝执行DDL")
    for table in ("rectifications", "rectification_events"):
        if conn.execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first() is not None:
            raise RuntimeError("存在整改记录或审计事件，拒绝自动回退；请先制定证据保留方案")
    op.drop_index("ix_rectification_events_rectification_id", table_name="rectification_events")
    op.drop_table("rectification_events")
    with op.batch_alter_table("rectifications") as batch:
        for name in ("submitted_by", "reviewed_by", "escalated_by"):
            batch.drop_constraint(f"fk_rectifications_{name}_users", type_="foreignkey")
        for name in ("acceptance_criteria", "handling_method", "after_text", "acceptance_reason", "residual_risk",
                     "escalation_reason", "contract_stage", "collaborators_json", "evidence_json", "submitted_by",
                     "reviewed_by", "escalated_by", "reviewed_at", "accepted_at", "escalated_at", "version"):
            batch.drop_column(name)
