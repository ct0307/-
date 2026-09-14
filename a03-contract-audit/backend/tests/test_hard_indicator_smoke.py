"""企业交付硬指标烟雾测试。"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

from cryptography.fernet import Fernet
from pydantic import ValidationError
import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import make_url
import yaml

from app.core.config import Settings
from app.db.session import Base
from app.models import models  # noqa: F401
from app.db import init_db as init_db_module


def _run_alembic(
    backend_dir: Path,
    database: Path,
    command: str,
    target: str,
) -> None:
    env = os.environ.copy()
    env.update({"DB_BACKEND": "sqlite", "SQLITE_PATH": database.as_posix()})
    completed = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", command, target],
        cwd=backend_dir,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_fresh_database_migration_matches_orm_metadata(tmp_path: Path):
    backend_dir = Path(__file__).resolve().parents[1]
    database = tmp_path / "migration-smoke.db"

    _run_alembic(backend_dir, database, "upgrade", "head")

    engine = create_engine(f"sqlite:///{database.as_posix()}")
    inspector = inspect(engine)
    migrated_tables = set(inspector.get_table_names()) - {"alembic_version"}
    assert migrated_tables == set(Base.metadata.tables)
    import_batch_columns = {column["name"] for column in inspector.get_columns("import_batches")}
    assert "request_fingerprint" in import_batch_columns
    audit_item_columns = {
        column["name"] for column in inspector.get_columns("audit_batch_items")
    }
    assert {"progress", "progress_stage"} <= audit_item_columns
    contract_foreign_keys = {
        (tuple(key["constrained_columns"]), key["referred_table"], tuple(key["referred_columns"]))
        for key in inspector.get_foreign_keys("contracts")
    }
    assert (("type_confirmed_by",), "users", ("id",)) in contract_foreign_keys
    assert (("deleted_by",), "users", ("id",)) in contract_foreign_keys

    _run_alembic(backend_dir, database, "downgrade", "base")
    remaining_tables = set(inspect(engine).get_table_names()) - {"alembic_version"}
    assert remaining_tables == set()
    engine.dispose()


def test_ocr_quality_migration_preserves_existing_contract(tmp_path: Path):
    backend_dir = Path(__file__).resolve().parents[1]
    database = tmp_path / "incremental.db"
    _run_alembic(backend_dir, database, "upgrade", "20260726_01")
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "INSERT INTO users (id, username, password_hash, role, department) "
            "VALUES (1, 'legacy', 'hash', 'legal', '法务部')"
        )
        connection.exec_driver_sql(
            "INSERT INTO contracts "
            "(id, filename, storage_path, contract_type, department, status, uploaded_by, elements_json) "
            "VALUES (1, 'legacy.pdf', '/legacy.pdf', '', '法务部', 'done', 1, '{}')"
        )

    _run_alembic(backend_dir, database, "upgrade", "head")

    with engine.connect() as connection:
        row = connection.exec_driver_sql(
            "SELECT parse_source, ocr_confidence, requires_review, review_reason "
            "FROM contracts WHERE id=1"
        ).mappings().one()
    assert row == {
        "parse_source": "native",
        "ocr_confidence": None,
        "requires_review": 0,
        "review_reason": None,
    }
    engine.dispose()


def test_postgres_startup_never_bypasses_alembic(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(init_db_module.settings, "DB_BACKEND", "postgres")
    monkeypatch.setattr(init_db_module.settings, "STORAGE_DIR", tmp_path.as_posix())
    monkeypatch.setattr(
        init_db_module.Base.metadata,
        "create_all",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("生产环境不得 create_all")),
    )
    monkeypatch.setattr(init_db_module, "_seed_users", lambda: None)

    init_db_module.init_db()


def test_production_startup_never_seeds_demo_accounts(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(init_db_module.settings, "DB_BACKEND", "sqlite")
    monkeypatch.setattr(init_db_module.settings, "APP_ENV", "prod")
    monkeypatch.setattr(init_db_module.settings, "STORAGE_DIR", tmp_path.as_posix())
    monkeypatch.setattr(init_db_module.Base.metadata, "create_all", lambda **_kwargs: None)
    monkeypatch.setattr(init_db_module, "_migrate_dev_columns", lambda: None)
    monkeypatch.setattr(
        init_db_module,
        "_seed_users",
        lambda: (_ for _ in ()).throw(AssertionError("生产环境不得灌入演示账号")),
    )

    init_db_module.init_db()


def test_production_settings_reject_insecure_defaults():
    with pytest.raises(ValidationError):
        Settings(
            APP_ENV="prod",
            DEBUG=False,
            DB_BACKEND="postgres",
            AUDIT_ASYNC=True,
            POSTGRES_PASSWORD="a03pass",
            JWT_SECRET="CHANGE_ME_IN_PRODUCTION",
            FILE_ENCRYPT_KEY="",
        )


def test_production_settings_accept_explicit_secrets():
    settings = Settings(
        APP_ENV="prod",
        DEBUG=False,
        DB_BACKEND="postgres",
        AUDIT_ASYNC=True,
        POSTGRES_PASSWORD="database-password-from-secret-store",
        JWT_SECRET="jwt-secret-with-at-least-thirty-two-characters",
        FILE_ENCRYPT_KEY=Fernet.generate_key().decode(),
    )

    assert settings.APP_ENV == "prod"


@pytest.mark.parametrize("seconds", [0, -1, 1800])
def test_audit_deadline_must_be_positive_and_shorter_than_worker_lease(seconds):
    with pytest.raises(ValidationError):
        Settings(AUDIT_DEADLINE_SECONDS=seconds)


def test_postgres_password_special_characters_are_url_encoded():
    password = "p@ss:/#%word-with-symbols"
    settings = Settings(DB_BACKEND="postgres", POSTGRES_PASSWORD=password)

    assert make_url(settings.database_url).password == password


def test_compose_runs_dedicated_recovery_scheduler():
    compose_path = Path(__file__).resolve().parents[2] / "docker-compose.yml"
    compose = yaml.safe_load(compose_path.read_text(encoding="utf-8"))

    scheduler = compose["services"]["scheduler"]
    assert "beat" in scheduler["command"]
    assert scheduler["depends_on"]["backend"]["condition"] == "service_healthy"
