from __future__ import annotations

import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    create_engine,
    func,
    inspect,
    select,
)
from sqlalchemy.orm import Session

from app.db import init_db as init_db_module
from app.db.session import Base
from app.models.models import ContractTypeProfile, LookupItem


CURRENT_CONTRACT_TYPES = (
    "软件开发外包合同",
    "技术服务合同",
    "采购合同",
    "销售合同",
    "劳动合同",
    "租赁合同",
    "保密协议",
    "合作协议",
    "服务协议",
    "框架协议",
    "技术开发合同",
    "合作合同",
    "服务合同",
    "劳务合同",
)


def _load_profile_migration():
    path = (
        Path(__file__).parents[1]
        / "alembic"
        / "versions"
        / "20260916_01_contract_type_profiles.py"
    )
    spec = importlib.util.spec_from_file_location("contract_type_profile_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _lookup_table(metadata: MetaData) -> Table:
    return Table(
        "lookup_items",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("category", String(32), nullable=False),
        Column("value", String(128), nullable=False),
        Column("sort_order", Integer, nullable=False, default=0),
        Column("created_at", DateTime(timezone=True), server_default=func.now()),
    )


def test_profile_migration_seeds_current_types_and_cascades():
    engine = create_engine("sqlite:///:memory:")
    metadata = MetaData()
    lookup_items = _lookup_table(metadata)
    metadata.create_all(engine)
    migration = _load_profile_migration()

    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        connection.execute(
            lookup_items.insert(),
            [
                {"category": "contract_type", "value": value, "sort_order": index}
                for index, value in enumerate(CURRENT_CONTRACT_TYPES)
            ],
        )
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()

        profiles = Table("contract_type_profiles", MetaData(), autoload_with=connection)
        rows = connection.execute(
            select(lookup_items.c.value, profiles.c.positive_signals_json)
            .join(profiles, profiles.c.lookup_item_id == lookup_items.c.id)
            .order_by(lookup_items.c.sort_order)
        ).all()
        assert [row.value for row in rows] == list(CURRENT_CONTRACT_TYPES)
        assert all(row.positive_signals_json != "[]" for row in rows)

        deleted_lookup_id = connection.scalar(
            select(lookup_items.c.id).where(lookup_items.c.value == "采购合同")
        )
        connection.execute(
            lookup_items.delete().where(lookup_items.c.id == deleted_lookup_id)
        )
        assert connection.scalar(
            select(func.count()).select_from(profiles).where(
                profiles.c.lookup_item_id == deleted_lookup_id
            )
        ) == 0

        migration.downgrade()
        assert "contract_type_profiles" not in inspect(connection).get_table_names()


def test_sqlite_dev_seed_is_idempotent(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    monkeypatch.setattr(init_db_module, "SessionLocal", lambda: Session(engine))

    init_db_module._seed_contract_type_profiles()
    init_db_module._seed_contract_type_profiles()

    with Session(engine) as db:
        lookups = db.query(LookupItem).filter_by(category="contract_type").all()
        profiles = db.query(ContractTypeProfile).all()
        assert {item.value for item in lookups} == set(CURRENT_CONTRACT_TYPES)
        assert len(profiles) == len(CURRENT_CONTRACT_TYPES)
