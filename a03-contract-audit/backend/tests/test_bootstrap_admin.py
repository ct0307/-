from types import SimpleNamespace
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core.security import verify_password
from app.core.config import Settings
from app.db.session import Base
from app.models.models import AuditLog, User
from scripts import bootstrap_admin


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_bootstrap_admin_creates_one_admin_without_logging_password(capsys):
    db = _session()

    result = bootstrap_admin.create_admin(
        db,
        username="ops-admin",
        password="Strong-pass-123!",
        config=SimpleNamespace(APP_ENV="dev", DB_BACKEND="sqlite"),
    )

    assert result.username == "ops-admin"
    assert result.role == "admin"
    assert verify_password("Strong-pass-123!", result.password_hash)
    assert "Strong-pass-123!" not in capsys.readouterr().out
    assert db.query(AuditLog).filter_by(action="bootstrap_admin").count() == 1


def test_bootstrap_admin_does_not_overwrite_existing_user():
    db = _session()
    original = bootstrap_admin.create_admin(
        db,
        username="ops-admin",
        password="Original-pass-123!",
        config=SimpleNamespace(APP_ENV="dev", DB_BACKEND="sqlite"),
    )
    db.expunge(original)

    with pytest.raises(bootstrap_admin.BootstrapAdminError, match="已存在"):
        bootstrap_admin.create_admin(
            db,
            username="ops-admin",
            password="Replacement-pass-999!",
            config=SimpleNamespace(APP_ENV="dev", DB_BACKEND="sqlite"),
        )

    current = db.query(User).filter_by(username="ops-admin").one()
    assert verify_password("Original-pass-123!", current.password_hash)
    assert not verify_password("Replacement-pass-999!", current.password_hash)


def test_bootstrap_admin_rejects_production_without_postgres_or_strong_secrets():
    db = _session()
    with pytest.raises(bootstrap_admin.BootstrapAdminError, match="生产"):
        bootstrap_admin.ensure_bootstrap_allowed(
            SimpleNamespace(APP_ENV="prod", DB_BACKEND="sqlite")
        )


@pytest.mark.parametrize("username", ["", " " * 3, "a" * 65])
def test_bootstrap_rejects_invalid_username_before_writing(username):
    with _session() as db:
        with pytest.raises(bootstrap_admin.BootstrapAdminError, match="用户名"):
            bootstrap_admin.create_admin(db, username=username, password="Strong-pass-123!", config=SimpleNamespace(APP_ENV="dev"))
        assert db.query(User).count() == 0


@pytest.mark.parametrize("password", ["", "short", "密" * 4, "a" * 73, "密" * 25, "CHANGE_ME_IN_PRODUCTION", "password123456"])
def test_bootstrap_rejects_weak_or_truncated_password_before_writing(password):
    with _session() as db:
        with pytest.raises(bootstrap_admin.BootstrapAdminError, match="密码"):
            bootstrap_admin.create_admin(db, username="ops", password=password, config=SimpleNamespace(APP_ENV="dev"))
        assert db.query(User).count() == 0


def test_bootstrap_reuses_the_production_validator(monkeypatch):
    calls = []
    config = Settings.model_construct(APP_ENV="prod")
    def reject(self):
        calls.append(self)
        raise ValueError("JWT_SECRET=secret-do-not-print")
    monkeypatch.setattr(Settings, "validate_production_security", reject)
    with pytest.raises(bootstrap_admin.BootstrapAdminError) as error:
        bootstrap_admin.ensure_bootstrap_allowed(config)
    assert calls == [config]
    assert "secret-do-not-print" not in str(error.value)


def test_bootstrap_rolls_back_user_when_audit_cannot_be_saved(monkeypatch):
    with _session() as db:
        from app.services import audit_log
        def fail(*args, **kwargs):
            raise OperationalError("secret-db-host", {}, Exception("secret-db-password"))
        monkeypatch.setattr(audit_log, "record", fail)
        with pytest.raises(bootstrap_admin.BootstrapAdminError):
            bootstrap_admin.create_admin(db, username="ops", password="Strong-pass-123!", config=SimpleNamespace(APP_ENV="dev"))
        assert db.query(User).count() == 0
        assert db.query(AuditLog).count() == 0


def test_bootstrap_cli_handles_database_failure_without_details(monkeypatch, capsys):
    db = _session()
    def fail(*args, **kwargs):
        raise OperationalError("secret-db-host", {}, Exception("secret-db-password"))
    monkeypatch.setattr(bootstrap_admin, "SessionLocal", lambda: db)
    monkeypatch.setattr(db, "query", fail)
    monkeypatch.setattr(bootstrap_admin.getpass, "getpass", lambda _prompt: "Strong-pass-123!")
    assert bootstrap_admin.main(["--username", "ops"]) == 1
    output = capsys.readouterr()
    assert "数据库" in output.err
    assert "secret-" not in output.err + output.out


def test_bootstrap_cli_unsafe_production_config_does_not_print_values():
    env = dict(os.environ, PYTHONIOENCODING="utf-8", APP_ENV="prod", DEBUG="true", DB_BACKEND="sqlite", JWT_SECRET="secret-do-not-print", POSTGRES_PASSWORD="secret-do-not-print", FILE_ENCRYPT_KEY="secret-do-not-print")
    result = subprocess.run([sys.executable, "-m", "scripts.bootstrap_admin", "--username", "ops"], env=env, text=True, encoding="utf-8", capture_output=True)
    assert result.returncode != 0
    assert "secret-do-not-print" not in result.stderr + result.stdout
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize("change", [
    {"DEBUG": True}, {"DB_BACKEND": "sqlite"}, {"AUDIT_ASYNC": False},
    {"JWT_SECRET": "short"}, {"FILE_ENCRYPT_KEY": "invalid"}, {"POSTGRES_PASSWORD": "a03pass"},
])
def test_bootstrap_production_rejects_every_unsafe_setting(change):
    from cryptography.fernet import Fernet
    values = dict(APP_ENV="prod", DEBUG=False, DB_BACKEND="postgres", AUDIT_ASYNC=True,
                  JWT_SECRET="independent-test-jwt-" * 2, POSTGRES_PASSWORD="independent-db-password",
                  FILE_ENCRYPT_KEY=Fernet.generate_key().decode())
    config = Settings.model_construct(**(values | change))
    with pytest.raises(bootstrap_admin.BootstrapAdminError, match="生产"):
        bootstrap_admin.ensure_bootstrap_allowed(config)


@pytest.mark.parametrize("password", ["sufficient12", "密" * 24])
def test_bootstrap_accepts_password_byte_boundaries(password):
    with _session() as db:
        user = bootstrap_admin.create_admin(db, username="a" * 64, password=password, config=SimpleNamespace(APP_ENV="dev"))
        assert verify_password(password, user.password_hash)


def test_bootstrap_concurrent_duplicate_keeps_one_user_and_one_audit(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'admin-test.db').as_posix()}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    def create():
        with Session(engine) as db:
            try:
                bootstrap_admin.create_admin(db, username="ops", password="Strong-pass-123!", config=SimpleNamespace(APP_ENV="dev"))
                return "created"
            except bootstrap_admin.BootstrapAdminError:
                return "refused"
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: create(), range(2)))
    assert sorted(results) == ["created", "refused"]
    with Session(engine) as db:
        assert db.query(User).count() == db.query(AuditLog).filter_by(action="bootstrap_admin").count() == 1


def test_bootstrap_cli_confirmation_mismatch_does_not_open_database(monkeypatch, capsys):
    passwords = iter(["Strong-pass-123!", "Other-pass-123!"])
    monkeypatch.setattr(bootstrap_admin.getpass, "getpass", lambda _prompt: next(passwords))
    def forbidden():
        pytest.fail("确认失败时不应访问数据库")
    monkeypatch.setattr(bootstrap_admin, "SessionLocal", forbidden)
    assert bootstrap_admin.main(["--username", "ops"]) == 2
    assert "不一致" in capsys.readouterr().err


def test_bootstrap_cli_does_not_echo_accidental_password_arguments(capsys):
    with pytest.raises(SystemExit) as error:
        bootstrap_admin.main(["--username", "ops", "--password", "secret-do-not-print"])
    assert error.value.code == 2
    assert "secret-do-not-print" not in capsys.readouterr().err


def test_bootstrap_cli_redacts_unexpected_initialization_error(monkeypatch, capsys):
    def fail():
        raise RuntimeError("secret-do-not-print")
    monkeypatch.setattr(bootstrap_admin, "_load_settings", fail)
    assert bootstrap_admin.main(["--username", "ops"]) == 1
    assert "secret-do-not-print" not in capsys.readouterr().err


def test_bootstrap_refuses_any_existing_administrator():
    with _session() as db:
        bootstrap_admin.create_admin(db, username="first-admin", password="Strong-pass-123!", config=SimpleNamespace(APP_ENV="dev"))
        with pytest.raises(bootstrap_admin.BootstrapAdminError, match="管理员已存在"):
            bootstrap_admin.create_admin(db, username="second-admin", password="Strong-pass-456!", config=SimpleNamespace(APP_ENV="dev"))
        assert db.query(User).count() == 1


def test_bootstrap_concurrent_different_usernames_still_create_only_first_admin(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'first-admin-test.db').as_posix()}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    def create(index):
        with Session(engine) as db:
            try:
                bootstrap_admin.create_admin(db, username=f"ops-{index}", password="Strong-pass-123!", config=SimpleNamespace(APP_ENV="dev"))
                return "created"
            except bootstrap_admin.BootstrapAdminError:
                return "refused"
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(create, range(2)))
    assert sorted(results) == ["created", "refused"]
    with Session(engine) as db:
        assert db.query(User).count() == db.query(AuditLog).filter_by(action="bootstrap_admin").count() == 1
