"""持久化合同类型分类规则。"""

import json

from alembic import op
import sqlalchemy as sa


revision = "20260916_01"
down_revision = "20260914_02"
branch_labels = None
depends_on = None


_PROFILE_SEEDS = (
    ("软件开发外包合同", ("软件开发", "软件外包", "系统开发"), ("软件开发", "系统开发", "源代码", "软件外包")),
    ("技术服务合同", ("技术服务", "技术支持", "技术维护"), ("技术服务", "技术支持", "技术维护")),
    ("采购合同", ("采购", "购置"), ("采购", "购置", "供货", "设备")),
    ("销售合同", ("销售", "出售"), ("销售", "出售", "售卖")),
    ("劳动合同", ("劳动",), ("劳动关系", "试用期", "工资")),
    ("租赁合同", ("租赁", "承租", "出租"), ("租赁", "承租", "出租")),
    ("保密协议", ("保密协议",), ("专项保密协议",)),
    ("合作协议", ("合作协议",), ("合作项目",)),
    ("服务协议", ("服务协议",), ("提供服务",)),
    ("框架协议", ("框架",), ("框架合作", "框架采购")),
    ("技术开发合同", ("技术开发", "研发"), ("技术开发", "研发", "技术成果")),
    ("合作合同", ("合作合同",), ("合作项目",)),
    ("服务合同", ("服务合同",), ("提供服务",)),
    ("劳务合同", ("劳务",), ("劳务", "劳务报酬", "劳务人员")),
)


def upgrade() -> None:
    op.create_table(
        "contract_type_profiles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("lookup_item_id", sa.Integer(), nullable=False),
        sa.Column("aliases_json", sa.Text(), server_default="[]", nullable=False),
        sa.Column(
            "positive_signals_json",
            sa.Text(),
            server_default="[]",
            nullable=False,
        ),
        sa.Column(
            "negative_signals_json",
            sa.Text(),
            server_default="[]",
            nullable=False,
        ),
        sa.Column(
            "enabled",
            sa.Boolean(),
            server_default=sa.true(),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["lookup_item_id"],
            ["lookup_items.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("lookup_item_id"),
    )
    op.create_index(
        "ix_contract_type_profiles_lookup_item_id",
        "contract_type_profiles",
        ["lookup_item_id"],
        unique=True,
    )
    _seed_profiles()


def _seed_profiles() -> None:
    connection = op.get_bind()
    lookup_items = sa.table(
        "lookup_items",
        sa.column("id", sa.Integer()),
        sa.column("category", sa.String()),
        sa.column("value", sa.String()),
        sa.column("sort_order", sa.Integer()),
    )
    profiles = sa.table(
        "contract_type_profiles",
        sa.column("lookup_item_id", sa.Integer()),
        sa.column("aliases_json", sa.Text()),
        sa.column("positive_signals_json", sa.Text()),
        sa.column("negative_signals_json", sa.Text()),
    )
    for sort_order, (value, aliases, positive_signals) in enumerate(_PROFILE_SEEDS):
        lookup_id = connection.scalar(
            sa.select(lookup_items.c.id).where(
                lookup_items.c.category == "contract_type",
                lookup_items.c.value == value,
            )
        )
        if lookup_id is None:
            connection.execute(
                lookup_items.insert().values(
                    category="contract_type",
                    value=value,
                    sort_order=sort_order,
                )
            )
            lookup_id = connection.scalar(
                sa.select(lookup_items.c.id).where(
                    lookup_items.c.category == "contract_type",
                    lookup_items.c.value == value,
                )
            )
        profile_exists = connection.scalar(
            sa.select(sa.func.count()).select_from(profiles).where(
                profiles.c.lookup_item_id == lookup_id
            )
        )
        if not profile_exists:
            connection.execute(
                profiles.insert().values(
                    lookup_item_id=lookup_id,
                    aliases_json=json.dumps(aliases, ensure_ascii=False),
                    positive_signals_json=json.dumps(
                        positive_signals,
                        ensure_ascii=False,
                    ),
                    negative_signals_json="[]",
                )
            )


def downgrade() -> None:
    op.drop_index(
        "ix_contract_type_profiles_lookup_item_id",
        table_name="contract_type_profiles",
    )
    op.drop_table("contract_type_profiles")
