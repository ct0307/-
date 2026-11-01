"""整改迁移在SQLite上的外键、数据保留及安全回退。"""
import importlib.util
import io
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


@pytest.fixture
def migration():
    path = Path(__file__).resolve().parents[1] / "alembic/versions/20261101_01_rectification_closure.py"
    spec = importlib.util.spec_from_file_location("closure_migration_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def legacy_db():
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE users (id INTEGER PRIMARY KEY)")
        conn.exec_driver_sql("CREATE TABLE risks (id INTEGER PRIMARY KEY)")
        conn.exec_driver_sql("CREATE TABLE rectifications (id INTEGER PRIMARY KEY, contract VARCHAR(255), risk_id INTEGER REFERENCES risks(id))")
    yield engine
    engine.dispose()


def test_sqlite_upgrade_adds_foreign_keys_and_preserves_legacy_row(migration, legacy_db):
    with legacy_db.begin() as conn:
        conn.exec_driver_sql("INSERT INTO rectifications (id, contract) VALUES (1, '历史合同')")
        with Operations.context(MigrationContext.configure(conn)):
            migration.upgrade()
        row = conn.exec_driver_sql("SELECT contract, acceptance_criteria, contract_stage, evidence_json, submitted_by, version FROM rectifications").one()
        assert tuple(row) == ("历史合同", "", "unknown", "[]", None, 1)
        foreign_keys = {tuple(item["constrained_columns"]) for item in sa.inspect(conn).get_foreign_keys("rectifications")}
        assert {("risk_id",), ("submitted_by",), ("reviewed_by",), ("escalated_by",)} <= foreign_keys


def test_empty_rectification_tables_can_downgrade(migration, legacy_db):
    with legacy_db.begin() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            migration.upgrade()
            migration.downgrade()
        assert "rectification_events" not in sa.inspect(conn).get_table_names()
        assert {column["name"] for column in sa.inspect(conn).get_columns("rectifications")} == {"id", "contract", "risk_id"}


@pytest.mark.parametrize("with_event", [False, True])
def test_nonempty_rectification_data_blocks_downgrade_before_any_drop(migration, legacy_db, with_event):
    with legacy_db.begin() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            migration.upgrade()
        conn.exec_driver_sql("INSERT INTO users (id) VALUES (1)")
        conn.exec_driver_sql("INSERT INTO rectifications (id, contract, acceptance_criteria) VALUES (1, '历史合同', '真实验收条件')")
        if with_event:
            conn.exec_driver_sql("INSERT INTO rectification_events (rectification_id, action, actor_id, actor, occurred_at, to_status, snapshot_json) VALUES (1, 'create', 1, 'legal', CURRENT_TIMESTAMP, '待处理', '{\"evidence\": []}')")
        with Operations.context(MigrationContext.configure(conn)):
            with pytest.raises(RuntimeError, match="存在整改记录或审计事件"):
                migration.downgrade()
        assert "rectification_events" in sa.inspect(conn).get_table_names()
        assert conn.exec_driver_sql("SELECT acceptance_criteria FROM rectifications WHERE id=1").scalar_one() == "真实验收条件"


def test_postgresql_offline_upgrade_preserves_named_foreign_keys(migration):
    buffer = io.StringIO()
    context = MigrationContext.configure(dialect_name="postgresql", opts={"as_sql": True, "output_buffer": buffer})
    with Operations.context(context):
        migration.upgrade()
    sql = buffer.getvalue()
    assert "CREATE TABLE rectification_events" in sql
    assert "ADD COLUMN version INTEGER DEFAULT '1' NOT NULL" in sql
    for field in ("submitted_by", "reviewed_by", "escalated_by"):
        assert f"ADD CONSTRAINT fk_rectifications_{field}_users FOREIGN KEY({field}) REFERENCES users (id)" in sql


def test_fresh_revision_matches_rectification_orm_columns_and_foreign_keys(tmp_path):
    from app.models.models import Rectification, RectificationEvent
    from tests.test_hard_indicator_smoke import _run_alembic
    backend_dir = Path(__file__).resolve().parents[1]
    database = tmp_path / "closure-metadata.db"
    _run_alembic(backend_dir, database, "upgrade", "head")
    engine = sa.create_engine(f"sqlite:///{database.as_posix()}")
    try:
        inspector = sa.inspect(engine)
        for model in (Rectification, RectificationEvent):
            table = model.__table__
            actual = {column["name"]: column for column in inspector.get_columns(table.name)}
            assert set(actual) == set(table.columns.keys())
            for column in table.columns:
                assert actual[column.name]["nullable"] == column.nullable
                assert isinstance(actual[column.name]["type"], type(column.type))
            actual_fks = {(tuple(key["constrained_columns"]), key["referred_table"], tuple(key["referred_columns"])) for key in inspector.get_foreign_keys(table.name)}
            orm_fks = {((key.parent.name,), key.column.table.name, (key.column.name,)) for key in table.foreign_keys}
            assert actual_fks == orm_fks
    finally:
        engine.dispose()


def test_postgresql_downgrade_locks_both_tables_before_reading(migration, monkeypatch):
    statements = []
    def execute(statement):
        statements.append(str(statement))
        # 首次检查发现真实记录，确保测试只观察锁和检查，不执行DDL。
        return SimpleNamespace(first=lambda: (1,))
    conn = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"), execute=execute,
        in_transaction=lambda: True)
    monkeypatch.setattr(migration, "op", SimpleNamespace(get_context=lambda: SimpleNamespace(as_sql=False), get_bind=lambda: conn))
    with pytest.raises(RuntimeError, match="存在整改记录或审计事件"):
        migration.downgrade()
    assert statements == [
        "LOCK TABLE rectifications, rectification_events IN ACCESS EXCLUSIVE MODE",
        "SELECT 1 FROM rectifications LIMIT 1",
    ]


@pytest.mark.parametrize("target", ["rectifications", "rectification_events"])
def test_sqlite_downgrade_blocks_concurrent_insert_after_empty_check(migration, tmp_path, target):
    path = tmp_path / "locked-downgrade.db"
    engine = sa.create_engine(f"sqlite:///{path.as_posix()}")
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql("CREATE TABLE users (id INTEGER PRIMARY KEY)")
            conn.exec_driver_sql("CREATE TABLE risks (id INTEGER PRIMARY KEY)")
            conn.exec_driver_sql("CREATE TABLE rectifications (id INTEGER PRIMARY KEY, contract VARCHAR(255), risk_id INTEGER REFERENCES risks(id))")
            with Operations.context(MigrationContext.configure(conn)):
                migration.upgrade()
        attempts = []
        def try_concurrent_insert(conn, cursor, statement, parameters, context, executemany):
            if statement != "SELECT 1 FROM rectifications LIMIT 1" or attempts:
                return
            attempts.append(target)
            # 单独DBAPI连接真正尝试写入，覆盖sqlite legacy模式不自动BEGIN的问题。
            with sqlite3.connect(path, timeout=0) as writer:
                with pytest.raises(sqlite3.OperationalError, match="locked"):
                    if target == "rectifications":
                        writer.execute("INSERT INTO rectifications (id, contract) VALUES (2, '并发整改')")
                    else:
                        writer.execute("INSERT INTO rectification_events (rectification_id, action, actor_id, actor, occurred_at, to_status, snapshot_json) VALUES (2, 'create', 1, 'legal', CURRENT_TIMESTAMP, '待处理', '{}')")
        sa.event.listen(engine, "after_cursor_execute", try_concurrent_insert)
        with engine.begin() as conn:
            with Operations.context(MigrationContext.configure(conn)):
                migration.downgrade()
            # 函数返回后、外层事务提交前，实际写锁仍须覆盖后续DDL窗口。
            with sqlite3.connect(path, timeout=0) as writer:
                with pytest.raises(sqlite3.OperationalError, match="locked"):
                    writer.execute("INSERT INTO rectifications (id, contract) VALUES (3, '事务结束前并发整改')")
        assert attempts == [target]
        assert "rectification_events" not in sa.inspect(engine).get_table_names()
    finally:
        engine.dispose()


def test_sqlite_autocommit_downgrade_refuses_unprotected_ddl(migration):
    engine = sa.create_engine("sqlite:///:memory:", isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            conn.exec_driver_sql("CREATE TABLE users (id INTEGER PRIMARY KEY)")
            conn.exec_driver_sql("CREATE TABLE risks (id INTEGER PRIMARY KEY)")
            conn.exec_driver_sql("CREATE TABLE rectifications (id INTEGER PRIMARY KEY, contract VARCHAR(255), risk_id INTEGER REFERENCES risks(id))")
            with Operations.context(MigrationContext.configure(conn)):
                migration.upgrade()
                with pytest.raises(RuntimeError, match="实际写事务"):
                    migration.downgrade()
            assert "rectification_events" in sa.inspect(conn).get_table_names()
    finally:
        engine.dispose()
