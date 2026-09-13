"""从智能收件箱创建审查批次的契约测试。"""

from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.v1.endpoints import batches, imports
from app.db.session import Base
from app.models.models import (
    AuditBatch,
    AuditBatchItem,
    AuditLog,
    Contract,
    ImportBatch,
    ImportBatchItem,
    User,
)
from app.schemas.batch import BatchFromImportRequest
from app.tasks import audit_tasks
from app.tasks.audit_tasks import run_contract_audit


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _user(db: Session) -> User:
    user = User(
        username="legal",
        password_hash="not-used",
        role="legal",
        department="法务部",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _import_item(
    db: Session,
    user: User,
    *,
    filename: str,
    contract_type: str,
    status: str = "ready",
) -> ImportBatchItem:
    batch = ImportBatch(
        owner_id=user.id,
        idempotency_key=f"import-{filename}",
        status="ready" if status == "ready" else "needs_attention",
        total=1,
        ready=1 if status == "ready" else 0,
    )
    contract = Contract(
        filename=filename,
        storage_path=f"storage/{filename}",
        contract_type=contract_type,
        department=user.department,
        uploaded_by=user.id,
        status="parsed",
    )
    item = ImportBatchItem(filename=filename, contract=contract, status=status)
    batch.items.append(item)
    db.add(batch)
    db.commit()
    db.refresh(item)
    return item


def test_create_audit_batch_from_ready_mixed_import_items(monkeypatch):
    db = _session()
    legal = _user(db)
    purchase_item = _import_item(
        db,
        legal,
        filename="采购合同.txt",
        contract_type="采购合同",
    )
    software_item = _import_item(
        db,
        legal,
        filename="开发协议.txt",
        contract_type="软件开发外包合同",
    )
    dispatched: list[tuple[int, list[str]]] = []
    monkeypatch.setattr(
        batches,
        "_dispatch_item",
        lambda item, dimensions: dispatched.append((item.id, dimensions)) or f"task-{item.id}",
    )

    result = batches.create_batch_from_import(
        body=BatchFromImportRequest(
            import_item_ids=[purchase_item.id, software_item.id],
            dimensions=["payment", "legal", "legal"],
        ),
        idempotency_key="audit-from-import-1",
        db=db,
        user=legal,
    )

    assert result.total == 2
    saved_types = [db.get(Contract, item.contract_id).contract_type for item in result.items]
    assert saved_types == ["采购合同", "软件开发外包合同"]
    assert [db.get(ImportBatchItem, item_id).status for item_id in [purchase_item.id, software_item.id]] == [
        "auditing",
        "auditing",
    ]
    assert all(item.import_item_id for item in db.query(AuditBatchItem).all())
    assert [dimensions for _, dimensions in dispatched] == [["legal", "payment"]] * 2
    log = db.query(AuditLog).filter(AuditLog.action == "batch_create_from_import").one()
    assert log.target == f"batch:{result.id}"


def test_batch_from_import_rejects_non_ready_item():
    db = _session()
    legal = _user(db)
    awaiting_item = _import_item(
        db,
        legal,
        filename="待确认.txt",
        contract_type="",
        status="awaiting_confirmation",
    )

    with pytest.raises(HTTPException) as error:
        batches.create_batch_from_import(
            BatchFromImportRequest(import_item_ids=[awaiting_item.id], dimensions=[]),
            "not-ready-key",
            db,
            legal,
        )

    assert error.value.status_code == 409
    assert error.value.detail["code"] == "IMPORT_ITEM_NOT_READY"


def test_delete_winning_race_prevents_audit_batch_creation(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'delete-create-race.db').as_posix()}")
    Base.metadata.create_all(engine)
    with Session(engine) as setup:
        legal = _user(setup)
        source_item = _import_item(
            setup,
            legal,
            filename="竞争删除.txt",
            contract_type="采购合同",
        )
        import_batch_id = source_item.batch_id
        import_item_id = source_item.id
        contract_id = source_item.contract_id
        user_id = legal.id

    class DeleteInterleavingSession(Session):
        def query(self, *entities, **kwargs):
            if (
                len(entities) == 1
                and entities[0] is AuditBatchItem.id
                and self.info.pop("delete_before_claim", False)
            ):
                with Session(engine) as deleting:
                    delete_user = deleting.get(User, user_id)
                    imports.delete_contract_draft(
                        import_batch_id,
                        import_item_id,
                        deleting,
                        delete_user,
                    )
            return super().query(*entities, **kwargs)

    db = DeleteInterleavingSession(engine)
    legal = db.get(User, user_id)
    db.info["delete_before_claim"] = True
    monkeypatch.setattr(batches, "_dispatch_item", lambda *_args: "task")

    with pytest.raises(HTTPException) as error:
        batches.create_batch_from_import(
            BatchFromImportRequest(import_item_ids=[import_item_id], dimensions=[]),
            "delete-create-race",
            db,
            legal,
        )

    assert error.value.status_code == 409
    db.rollback()
    db.close()
    with Session(engine) as check:
        contract = check.get(Contract, contract_id)
        active_jobs = check.query(AuditBatchItem).filter(
            AuditBatchItem.contract_id == contract_id,
            AuditBatchItem.status.in_(
                {"queued", "parsing", "reviewing", "validating", "auditing"}
            ),
        ).count()
        assert contract.deleted_at is not None
        assert contract.status != "reviewing"
        assert active_jobs == 0


@pytest.mark.parametrize(
    ("winner_dimensions", "same_fingerprint"),
    [([], True), (["legal"], False)],
    ids=["same-fingerprint", "different-fingerprint"],
)
def test_concurrent_idempotency_replays_only_matching_batch(
    monkeypatch,
    tmp_path,
    winner_dimensions,
    same_fingerprint,
):
    engine = create_engine(
        f"sqlite:///{(tmp_path / f'idempotency-{same_fingerprint}.db').as_posix()}"
    )
    Base.metadata.create_all(engine)
    with Session(engine) as setup:
        legal = _user(setup)
        source_item = _import_item(
            setup,
            legal,
            filename="幂等竞争.txt",
            contract_type="采购合同",
        )
        import_item_id = source_item.id
        contract_id = source_item.contract_id
        user_id = legal.id

    original_claim = batches.claim_contract_for_audit
    winner_results = []
    interleaved = False

    def create_winner_before_loser_claim(db, **kwargs):
        nonlocal interleaved
        if not interleaved:
            interleaved = True
            with Session(engine) as winner_db:
                winner_user = winner_db.get(User, user_id)
                winner_results.append(batches.create_batch_from_import(
                    BatchFromImportRequest(
                        import_item_ids=[import_item_id],
                        dimensions=winner_dimensions,
                    ),
                    "concurrent-idempotency",
                    winner_db,
                    winner_user,
                ))
        return original_claim(db, **kwargs)

    monkeypatch.setattr(batches, "claim_contract_for_audit", create_winner_before_loser_claim)
    monkeypatch.setattr(batches, "_dispatch_item", lambda *_args: "task")
    with Session(engine) as loser_db:
        loser_user = loser_db.get(User, user_id)
        request = BatchFromImportRequest(import_item_ids=[import_item_id], dimensions=[])
        if same_fingerprint:
            loser_result = batches.create_batch_from_import(
                request,
                "concurrent-idempotency",
                loser_db,
                loser_user,
            )
            assert loser_result.id == winner_results[0].id
        else:
            with pytest.raises(HTTPException) as error:
                batches.create_batch_from_import(
                    request,
                    "concurrent-idempotency",
                    loser_db,
                    loser_user,
                )
            assert error.value.status_code == 409
            assert error.value.detail["code"] == "IDEMPOTENCY_CONFLICT"

    with Session(engine) as check:
        assert check.query(AuditBatch).count() == 1
        assert check.query(AuditBatchItem).count() == 1
        assert check.get(Contract, contract_id).audit_generation == 1


@pytest.mark.parametrize(
    ("winner_key", "winner_dimensions", "expected"),
    [
        ("early-idempotency", [], "replay"),
        ("early-idempotency", ["legal"], "IDEMPOTENCY_CONFLICT"),
        ("different-active-key", [], "CONTRACT_ALREADY_AUDITING"),
    ],
    ids=["same-fingerprint", "different-fingerprint", "different-key"],
)
def test_active_precheck_replays_only_matching_concurrent_request(
    monkeypatch,
    tmp_path,
    winner_key,
    winner_dimensions,
    expected,
):
    engine = create_engine(
        f"sqlite:///{(tmp_path / f'early-{expected}.db').as_posix()}"
    )
    Base.metadata.create_all(engine)
    with Session(engine) as setup:
        legal = _user(setup)
        source_item = _import_item(
            setup,
            legal,
            filename="早期竞争.txt",
            contract_type="采购合同",
        )
        import_item_id = source_item.id
        contract_id = source_item.contract_id
        user_id = legal.id

    winner_results = []

    class ActiveInterleavingSession(Session):
        def query(self, *entities, **kwargs):
            if (
                len(entities) == 1
                and entities[0] is AuditBatchItem.id
                and self.info.pop("create_before_active_check", False)
            ):
                with Session(engine) as winner_db:
                    winner_user = winner_db.get(User, user_id)
                    winner_results.append(batches.create_batch_from_import(
                        BatchFromImportRequest(
                            import_item_ids=[import_item_id],
                            dimensions=winner_dimensions,
                        ),
                        winner_key,
                        winner_db,
                        winner_user,
                    ))
            return super().query(*entities, **kwargs)

    monkeypatch.setattr(batches, "_dispatch_item", lambda *_args: "task")
    with ActiveInterleavingSession(engine) as loser_db:
        loser_user = loser_db.get(User, user_id)
        loser_db.info["create_before_active_check"] = True
        request = BatchFromImportRequest(import_item_ids=[import_item_id], dimensions=[])
        if expected == "replay":
            result = batches.create_batch_from_import(
                request,
                "early-idempotency",
                loser_db,
                loser_user,
            )
            assert result.id == winner_results[0].id
        else:
            with pytest.raises(HTTPException) as error:
                batches.create_batch_from_import(
                    request,
                    "early-idempotency",
                    loser_db,
                    loser_user,
                )
            assert error.value.status_code == 409
            assert error.value.detail["code"] == expected

    with Session(engine) as check:
        assert check.query(AuditBatch).count() == 1
        assert check.query(AuditBatchItem).count() == 1
        assert check.get(Contract, contract_id).audit_generation == 1


def test_batch_from_import_rejects_reused_key_with_different_items(monkeypatch):
    db = _session()
    legal = _user(db)
    first_item = _import_item(db, legal, filename="一.txt", contract_type="采购合同")
    second_item = _import_item(db, legal, filename="二.txt", contract_type="租赁合同")
    monkeypatch.setattr(batches, "_dispatch_item", lambda *_args: "task")

    batches.create_batch_from_import(
        BatchFromImportRequest(import_item_ids=[first_item.id], dimensions=[]),
        "same-audit-key",
        db,
        legal,
    )

    with pytest.raises(HTTPException) as error:
        batches.create_batch_from_import(
            BatchFromImportRequest(import_item_ids=[second_item.id], dimensions=[]),
            "same-audit-key",
            db,
            legal,
        )

    assert error.value.status_code == 409


@pytest.mark.parametrize("audit_status", ["done", "review_required"])
def test_audit_task_writes_import_item_status_back(monkeypatch, audit_status):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        legal = _user(db)
        source_item = _import_item(
            db,
            legal,
            filename="成功.txt",
            contract_type="采购合同",
            status="auditing",
        )
        audit_batch = AuditBatch(
            owner_id=legal.id,
            department=legal.department,
            idempotency_key="write-back-success",
        )
        audit_item = AuditBatchItem(
            contract_id=source_item.contract_id,
            import_item_id=source_item.id,
            filename=source_item.filename,
        )
        audit_batch.items.append(audit_item)
        db.add(audit_batch)
        db.commit()
        contract_id, audit_item_id, source_item_id = (
            source_item.contract_id,
            audit_item.id,
            source_item.id,
        )

    def fake_run_audit(session, _contract, **kwargs):
        item = session.get(AuditBatchItem, kwargs["batch_item_id"])
        item.status = audit_status
        item.finished_at = datetime.now(timezone.utc)
        session.commit()
        return {"status": audit_status, "risk_count": 0, "cross_checks": []}

    monkeypatch.setattr(audit_tasks, "SessionLocal", lambda: Session(engine))
    monkeypatch.setattr(audit_tasks, "run_audit", fake_run_audit)

    result = run_contract_audit.run(contract_id, ["legal"], audit_item_id)

    with Session(engine) as db:
        assert result["status"] == audit_status
        assert db.get(ImportBatchItem, source_item_id).status == "done"


def test_failed_audit_returns_import_item_to_ready(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        legal = _user(db)
        source_item = _import_item(
            db,
            legal,
            filename="失败.txt",
            contract_type="采购合同",
            status="auditing",
        )
        audit_batch = AuditBatch(
            owner_id=legal.id,
            department=legal.department,
            idempotency_key="write-back-failure",
        )
        audit_item = AuditBatchItem(
            contract_id=source_item.contract_id,
            import_item_id=source_item.id,
            filename=source_item.filename,
        )
        audit_batch.items.append(audit_item)
        db.add(audit_batch)
        db.commit()
        contract_id, audit_item_id, source_item_id = (
            source_item.contract_id,
            audit_item.id,
            source_item.id,
        )

    monkeypatch.setattr(audit_tasks, "SessionLocal", lambda: Session(engine))
    monkeypatch.setattr(
        audit_tasks,
        "run_audit",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("audit failed")),
    )

    with pytest.raises(RuntimeError):
        run_contract_audit.run(contract_id, ["legal"], audit_item_id)

    with Session(engine) as db:
        assert db.get(ImportBatchItem, source_item_id).status == "ready"


def test_stale_from_import_worker_returns_source_to_ready_and_allows_recreate(
    monkeypatch, tmp_path
):
    engine = create_engine(f"sqlite:///{(tmp_path / 'stale-from-import.db').as_posix()}")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        legal = _user(db)
        source_item = _import_item(
            db,
            legal,
            filename="陈旧导入.txt",
            contract_type="采购合同",
        )
        monkeypatch.setattr(batches, "_dispatch_item", lambda *_args: "task-1")
        first = batches.create_batch_from_import(
            BatchFromImportRequest(
                import_item_ids=[source_item.id], dimensions=["payment"]
            ),
            "stale-from-import-first",
            db,
            legal,
        )
        audit_item = db.query(AuditBatchItem).filter(
            AuditBatchItem.batch_id == first.id,
        ).one()
        contract_id = source_item.contract_id
        audit_item_id = audit_item.id
        source_item_id = source_item.id

    # 新 generation 已经完成，旧 worker 此时才启动。
    with Session(engine) as newer:
        contract = newer.get(Contract, contract_id)
        contract.audit_generation = 2
        contract.status = "done"
        newer.commit()

    monkeypatch.setattr(audit_tasks, "SessionLocal", lambda: Session(engine))
    result = run_contract_audit.run(contract_id, ["payment"], audit_item_id)

    assert result == {"contract_id": contract_id, "status": "stale"}
    with Session(engine) as verify:
        saved_contract = verify.get(Contract, contract_id)
        saved_item = verify.get(AuditBatchItem, audit_item_id)
        saved_source = verify.get(ImportBatchItem, source_item_id)
        assert (saved_contract.audit_generation, saved_contract.status) == (2, "done")
        assert saved_item.status == "failed"
        assert saved_item.error_code == "STALE_AUDIT_RUN"
        assert saved_source.status == "ready"
        assert saved_source.batch.status == "ready"

        monkeypatch.setattr(batches, "_dispatch_item", lambda *_args: "task-2")
        recreated = batches.create_batch_from_import(
            BatchFromImportRequest(
                import_item_ids=[source_item_id], dimensions=["payment"]
            ),
            "stale-from-import-second",
            verify,
            verify.get(User, saved_source.batch.owner_id),
        )
        assert recreated.total == 1
        assert verify.get(ImportBatchItem, source_item_id).status == "auditing"


def test_stale_worker_does_not_rewind_completed_import_item(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'stale-completed-import.db').as_posix()}")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        legal = _user(db)
        source_item = _import_item(db, legal, filename="已完成导入.txt", contract_type="采购合同")
        monkeypatch.setattr(batches, "_dispatch_item", lambda *_args: "task-done")
        batch = batches.create_batch_from_import(
            BatchFromImportRequest(import_item_ids=[source_item.id], dimensions=["payment"]),
            "stale-completed-import",
            db,
            legal,
        )
        audit_item = db.query(AuditBatchItem).filter(AuditBatchItem.batch_id == batch.id).one()
        contract_id = source_item.contract_id
        audit_item_id = audit_item.id
        source_item_id = source_item.id

    with Session(engine) as db:
        source = db.get(ImportBatchItem, source_item_id)
        source.status = "done"
        contract = db.get(Contract, contract_id)
        contract.audit_generation = 2
        contract.status = "done"
        db.commit()

    monkeypatch.setattr(audit_tasks, "SessionLocal", lambda: Session(engine))
    assert run_contract_audit.run(contract_id, ["payment"], audit_item_id)["status"] == "stale"
    with Session(engine) as db:
        assert db.get(ImportBatchItem, source_item_id).status == "done"
