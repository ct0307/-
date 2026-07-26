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


def _run_alembic(backend_dir: Path, database: Path, command: str) -> None:
    env = os.environ.copy()
    env.update({"DB_BACKEND": "sqlite", "SQLITE_PATH": database.as_posix()})
    completed = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", command, "head" if command == "upgrade" else "base"],
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

    _run_alembic(backend_dir, database, "upgrade")

    engine = create_engine(f"sqlite:///{database.as_posix()}")
    migrated_tables = set(inspect(engine).get_table_names()) - {"alembic_version"}
    assert migrated_tables == set(Base.metadata.tables)

    _run_alembic(backend_dir, database, "downgrade")
    remaining_tables = set(inspect(engine).get_table_names()) - {"alembic_version"}
    assert remaining_tables == set()
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
