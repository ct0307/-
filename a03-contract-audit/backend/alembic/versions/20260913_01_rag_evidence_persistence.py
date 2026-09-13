"""持久化合同条款、来源锚点与风险检索轨迹。"""

from alembic import op
import sqlalchemy as sa


revision = "20260913_01"
down_revision = "20260912_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "contract_clauses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "contract_id",
            sa.Integer(),
            sa.ForeignKey("contracts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("audit_generation", sa.Integer(), server_default="0", nullable=False),
        sa.Column("chunk_id", sa.String(64), nullable=False),
        sa.Column("clause_id", sa.String(128), server_default="", nullable=False),
        sa.Column("clause_path_json", sa.Text(), server_default="[]", nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("block_type", sa.String(32), server_default="clause", nullable=False),
        sa.Column("char_start", sa.Integer(), nullable=True),
        sa.Column("char_end", sa.Integer(), nullable=True),
        sa.Column("parent_chunk_id", sa.String(64), nullable=True),
        sa.Column("previous_chunk_id", sa.String(64), nullable=True),
        sa.Column("next_chunk_id", sa.String(64), nullable=True),
        sa.Column("source_anchors_json", sa.Text(), server_default="[]", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "contract_id",
            "audit_generation",
            "chunk_id",
            name="uq_contract_clauses_generation_chunk",
        ),
    )
    op.create_index(
        "ix_contract_clauses_contract_id", "contract_clauses", ["contract_id"]
    )
    op.create_index("ix_contract_clauses_chunk_id", "contract_clauses", ["chunk_id"])

    op.add_column("risks", sa.Column("claim_id", sa.String(64), nullable=True))
    op.add_column(
        "risks",
        sa.Column(
            "claim_status",
            sa.String(24),
            server_default="pending_evidence",
            nullable=False,
        ),
    )
    op.add_column("risks", sa.Column("source_window_id", sa.String(64), nullable=True))
    for column_name in (
        "source_clause_ids_json",
        "evidence_ids_json",
        "retrieval_attempts_json",
        "contract_evidence_json",
    ):
        op.add_column(
            "risks",
            sa.Column(column_name, sa.Text(), server_default="[]", nullable=False),
        )
    op.create_index("ix_risks_claim_id", "risks", ["claim_id"])


def downgrade() -> None:
    op.drop_index("ix_risks_claim_id", table_name="risks")
    for column_name in (
        "contract_evidence_json",
        "retrieval_attempts_json",
        "evidence_ids_json",
        "source_clause_ids_json",
        "source_window_id",
        "claim_status",
        "claim_id",
    ):
        op.drop_column("risks", column_name)

    op.drop_index("ix_contract_clauses_chunk_id", table_name="contract_clauses")
    op.drop_index("ix_contract_clauses_contract_id", table_name="contract_clauses")
    op.drop_table("contract_clauses")
