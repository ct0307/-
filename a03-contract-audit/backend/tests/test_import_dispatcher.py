"""本地导入派发与进程重启恢复的行为回归。"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Event
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import Base
from app.models.models import ImportBatch, ImportBatchItem, User
from app.tasks import dispatcher, import_tasks


@pytest.fixture
def import_db(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'imports.db').as_posix()}")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = User(username="导入恢复测试", password_hash="x", role="legal")
        db.add(user)
        db.flush()
        batch = ImportBatch(owner_id=user.id, idempotency_key="recovery")
        db.add(batch)
        db.commit()
        batch_id = batch.id
    yield engine, batch_id
    engine.dispose()


def add_items(import_db, statuses, *, age_minutes=1):
    engine, batch_id = import_db
    with Session(engine) as db:
        items = [ImportBatchItem(
            batch_id=batch_id, filename=f"测试{index}.txt", status=status,
            attempts=2, updated_at=datetime.now(timezone.utc) - timedelta(minutes=age_minutes),
        ) for index, status in enumerate(statuses)]
        db.add_all(items)
        db.commit()
        return [item.id for item in items]


@pytest.mark.parametrize("status,age_minutes", [("queued", 1), ("parsing", 10), ("parsing", 1)])
def test_restart_recovers_unfinished_imports_even_after_short_downtime(import_db, status, age_minutes):
    engine, _ = import_db
    item_id, = add_items(import_db, [status], age_minutes=age_minutes)
    received = []

    def dispatch(saved_id):
        # 新执行器必须能在独立事务中读到已提交的待解析状态。
        with Session(engine) as db:
            item = db.get(ImportBatchItem, saved_id)
            assert item.status == "queued"
            assert item.attempts == 2
        received.append(saved_id)
        return "local-import:new"

    assert dispatcher.recover_local_import_items(
        session_factory=lambda: Session(engine), dispatch=dispatch,
    ) == 1
    assert received == [item_id]


def test_restart_preserves_terminal_and_audit_states(import_db):
    engine, _ = import_db
    statuses = ["ready", "awaiting_confirmation", "deleted", "done", "failed", "auditing"]
    item_ids = add_items(import_db, statuses, age_minutes=10)
    received = []
    assert dispatcher.recover_local_import_items(
        session_factory=lambda: Session(engine), dispatch=received.append,
    ) == 0
    assert received == []
    with Session(engine) as db:
        assert [db.get(ImportBatchItem, item_id).status for item_id in item_ids] == statuses


def test_failed_dispatch_remains_recoverable_without_blocking_other_items(import_db):
    engine, _ = import_db
    failed_id, good_id = add_items(import_db, ["queued", "queued"])
    received = []

    def dispatch(item_id):
        if item_id == failed_id:
            raise RuntimeError("测试执行器不可用")
        received.append(item_id)
        return "local-import:new"

    assert dispatcher.recover_local_import_items(
        session_factory=lambda: Session(engine), dispatch=dispatch,
    ) == 1
    assert received == [good_id]
    with Session(engine) as db:
        failed = db.get(ImportBatchItem, failed_id)
        assert failed.status == "queued"
        assert failed.error_code == "DISPATCH_PENDING"
        assert failed.attempts == 2


def test_restart_recovers_more_than_one_page_without_repeating_items(import_db):
    engine, _ = import_db
    item_ids = add_items(import_db, ["queued"] * 501)
    received = []
    assert dispatcher.recover_local_import_items(
        session_factory=lambda: Session(engine), dispatch=received.append,
    ) == 501
    assert received == item_ids


def test_import_parse_starts_while_audit_executor_is_busy(monkeypatch):
    audit_started, release_audit, parsed = Event(), Event(), Event()
    item_ids = []

    def audit(*_args):
        audit_started.set()
        release_audit.wait(5)

    def parse(item_id):
        item_ids.append(item_id)
        parsed.set()

    monkeypatch.setattr(settings, "AUDIT_ASYNC", False)
    monkeypatch.setattr(dispatcher, "_run_local", audit)
    monkeypatch.setattr(import_tasks.parse_import_item, "run", parse)
    with ThreadPoolExecutor(max_workers=1) as audits, ThreadPoolExecutor(max_workers=4) as imports:
        monkeypatch.setattr(dispatcher, "_local_executor", audits)
        monkeypatch.setattr(dispatcher, "_import_executor", imports)
        try:
            dispatcher.dispatch_audit_ids(1, ["legal"], 1)
            assert audit_started.wait(2)
            assert dispatcher.dispatch_import_item(42).startswith("local-import:")
            assert parsed.wait(2), "导入解析不应排在长时间审查之后"
            assert item_ids == [42]
        finally:
            release_audit.set()


def test_async_import_still_uses_celery(monkeypatch):
    received = []

    def delay(item_id):
        received.append(item_id)
        return SimpleNamespace(id="celery-import-42")

    monkeypatch.setattr(settings, "AUDIT_ASYNC", True)
    monkeypatch.setattr(import_tasks.parse_import_item, "delay", delay)
    assert dispatcher.dispatch_import_item(42) == "celery-import-42"
    assert received == [42]
