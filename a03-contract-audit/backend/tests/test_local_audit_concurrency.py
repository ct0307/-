"""本地受控调度：合成负载不代表真实模型吞吐或质量验收。"""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event, Lock
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.core.config import Settings, settings
from app.db.session import Base
from app.models.models import AuditBatch, AuditBatchItem, Contract, User
from app.services.audit import runner
from app.services.audit.result_quality import AuditCoverage
from app.services.parser.extractor import DocumentParseResult
from app.tasks import audit_tasks, dispatcher


def test_local_concurrency_defaults_to_two():
    value = getattr(Settings(_env_file=None), "AUDIT_LOCAL_CONCURRENCY", None)
    assert value == 2


@pytest.mark.parametrize("workers", [0, 5, -1])
def test_local_concurrency_rejects_unbounded_values(workers):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, AUDIT_LOCAL_CONCURRENCY=workers)


def test_two_contracts_start_before_the_first_finishes(monkeypatch):
    assert "AUDIT_LOCAL_CONCURRENCY" in Settings.model_fields, "缺少受控合同并发配置"
    monkeypatch.setattr(settings, "AUDIT_ASYNC", False)
    monkeypatch.setattr(settings, "AUDIT_LOCAL_CONCURRENCY", 2, raising=False)
    second_started, release = Event(), Event()
    active = 0
    peak = 0
    started = []
    lock = Lock()

    def compute(contract_id, dimensions, item_id):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
            started.append(contract_id)
            if active == 2:
                second_started.set()
        try:
            assert release.wait(5), "测试必须释放已开始的工作线程"
        finally:
            with lock:
                active -= 1

    monkeypatch.setattr(dispatcher, "_run_local", compute)
    with dispatcher._create_local_audit_executor() as pool:
        monkeypatch.setattr(dispatcher, "_local_executor", pool)
        try:
            ids = [dispatcher.dispatch_audit_ids(i, ["legal"], i) for i in range(3)]
            assert second_started.wait(2), "第二份合同不应等待第一份完成"
            with lock:
                assert len(started) == 2, "第三份应排队，不能绕过并发上限"
            assert all(task_id.startswith("local:") for task_id in ids)
            assert len(set(ids)) == 3
        finally:
            release.set()
    assert sorted(started) == [0, 1, 2]
    assert peak == 2


@pytest.mark.parametrize("workers", [1, 2, 4])
def test_fifty_two_sqlite_tasks_publish_independent_results(monkeypatch, tmp_path, workers):
    """真实SQLite/任务领取/进度/发布，替换计算边界，不调用模型或解析文件。"""
    assert "AUDIT_LOCAL_CONCURRENCY" in Settings.model_fields, "缺少受控合同并发配置"
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'concurrent.db').as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 15},
    )
    Base.metadata.create_all(engine)
    pairs = []
    with Session(engine) as db:
        user = User(username="合成并发验收", password_hash="unused", role="legal", department="测试")
        db.add(user)
        db.flush()
        batch = AuditBatch(owner_id=user.id, department="测试", idempotency_key="synthetic-52", total=52)
        db.add(batch)
        db.flush()
        for index in range(52):
            contract = Contract(
                filename=f"synthetic-{index}.txt", storage_path="unused",
                contract_type="采购合同", department="测试", uploaded_by=user.id,
            )
            db.add(contract)
            db.flush()
            item = AuditBatchItem(batch_id=batch.id, contract_id=contract.id, filename=contract.filename)
            db.add(item)
            db.flush()
            pairs.append((contract.id, item.id))
        db.commit()

    lock = Lock()
    entered, release = Event(), Event()
    active = peak = 0
    visits = []
    failure_id = pairs[7][0]

    def synthetic_compute(db, *, contract_id, progress_callback=None, **kwargs):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(active, peak)
            visits.append(contract_id)
            if active == workers:
                entered.set()
        try:
            assert release.wait(10), "应能启动配置数量的合同"
            if contract_id == failure_id:
                raise RuntimeError("合成单任务失败")
            progress_callback(55, "reviewing")
            return {
                "risk_count": 0, "cross_checks": [], "workflow": {},
                "ocr_confidence": None,
                "_parsed": DocumentParseResult(f"合成合同 {contract_id}，仅用于调度与发布验证。", "native"),
                "_risks": [], "_issues": [], "_coverage": AuditCoverage(1, 1),
                "_timings": {},
            }
        finally:
            with lock:
                active -= 1

    monkeypatch.setattr(settings, "AUDIT_ASYNC", False)
    monkeypatch.setattr(settings, "AUDIT_LOCAL_CONCURRENCY", workers, raising=False)
    monkeypatch.setattr(audit_tasks, "SessionLocal", lambda: Session(engine))
    monkeypatch.setattr(runner, "_compute_audit", synthetic_compute)
    try:
        with dispatcher._create_local_audit_executor() as pool:
            monkeypatch.setattr(dispatcher, "_local_executor", pool)
            try:
                for contract_id, item_id in pairs:
                    dispatcher.dispatch_audit_ids(contract_id, ["legal", "payment"], item_id)
                assert entered.wait(5), "配置的合同并发应在计算阶段实际生效"
            finally:
                release.set()
        with Session(engine) as db:
            rows = db.query(AuditBatchItem).order_by(AuditBatchItem.id).all()
            assert len(rows) == 52
            assert sum(row.status == "done" for row in rows) == 51
            failed = [row for row in rows if row.status == "failed"]
            assert len(failed) == 1 and failed[0].contract_id == failure_id
            assert failed[0].error_code == "AUDIT_INTERNAL_ERROR"
            assert all(row.started_at and row.finished_at for row in rows)
            assert all(row.execution_token is None and row.lease_expires_at is None for row in rows)
            assert sorted(visits) == sorted(contract_id for contract_id, _ in pairs)
            assert peak == workers
    finally:
        engine.dispose()


def test_async_branch_keeps_celery_dispatch(monkeypatch):
    received = []

    def delay(*args):
        received.append(args)
        return SimpleNamespace(id="celery-isolated")

    monkeypatch.setattr(settings, "AUDIT_ASYNC", True)
    monkeypatch.setattr(audit_tasks.run_contract_audit, "delay", delay)
    assert dispatcher.dispatch_audit_ids(3, ["legal"], 9) == "celery-isolated"
    assert received == [(3, ["legal"], 9)]


def test_duplicate_sqlite_delivery_only_computes_once(monkeypatch, tmp_path):
    """两线程都读到queued后再同时竞争领取，不能靠SQLite忽略的行锁。"""
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'duplicate.db').as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 10},
    )
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = User(username="重复派发", password_hash="unused", role="legal", department="测试")
        db.add(user)
        db.flush()
        contract = Contract(filename="synthetic.txt", storage_path="unused", uploaded_by=user.id)
        batch = AuditBatch(owner_id=user.id, department="测试", idempotency_key="duplicate")
        db.add_all([contract, batch])
        db.flush()
        item = AuditBatchItem(batch_id=batch.id, contract_id=contract.id, filename=contract.filename)
        db.add(item)
        db.commit()
        contract_id, item_id = contract.id, item.id

    barrier = Barrier(2)
    visits = []
    lock = Lock()

    class RaceSession(Session):
        pass

    @event.listens_for(RaceSession, "loaded_as_persistent")
    def synchronize_initial_read(db, instance):
        if isinstance(instance, AuditBatchItem) and not db.info.get("read_synchronized"):
            db.info["read_synchronized"] = True
            barrier.wait(timeout=5)

    def synthetic_compute(db, *, contract_id, **kwargs):
        with lock:
            visits.append(contract_id)
        return {
            "risk_count": 0, "cross_checks": [], "workflow": {}, "ocr_confidence": None,
            "_parsed": DocumentParseResult("仅用于测试重复任务领取的合成文本。", "native"),
            "_risks": [], "_issues": [], "_coverage": AuditCoverage(1, 1), "_timings": {},
        }

    monkeypatch.setattr(audit_tasks, "SessionLocal", lambda: RaceSession(engine))
    monkeypatch.setattr(runner, "_compute_audit", synthetic_compute)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(audit_tasks.run_contract_audit.run, contract_id, ["legal"], item_id) for _ in range(2)]
            # 记录异常，先检查重复计算；失败保护不应掩盖多次出站。
            results = []
            for future in futures:
                try:
                    results.append(future.result(timeout=15))
                except Exception as exc:
                    results.append(type(exc).__name__)
        assert visits == [contract_id], "同一任务只能取得一次计算执行权"
        assert all(isinstance(result, dict) for result in results), results
        with Session(engine) as db:
            assert db.get(AuditBatchItem, item_id).status == "done"
    finally:
        engine.dispose()
