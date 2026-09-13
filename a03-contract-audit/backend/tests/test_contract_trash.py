"""合同软删除、回收站与到期清理测试。"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.v1.endpoints import admin, contracts
from app.db.session import Base
from app.models.models import Contract, ImportBatch, ImportBatchItem, User
from app.services.imports.trash import purge_expired_contract_files
from app.services.report.exporter import contracts_metadata, report_summary


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _seed_deleted_contract(
    db: Session,
    *,
    deleted_at: datetime,
    storage_path: str,
    username: str = "legal",
) -> tuple[User, Contract, ImportBatchItem]:
    owner = User(
        username=username,
        password_hash="not-used",
        role="legal",
        department="法务部",
    )
    db.add(owner)
    db.flush()
    contract = Contract(
        filename="待清理合同.txt",
        storage_path=storage_path,
        contract_type="采购合同",
        department="法务部",
        status="uploaded",
        uploaded_by=owner.id,
        deleted_at=deleted_at,
        deleted_by=owner.id,
    )
    batch = ImportBatch(owner_id=owner.id, idempotency_key="trash-seed")
    item = ImportBatchItem(filename=contract.filename, contract=contract, status="deleted")
    batch.items.append(item)
    db.add(batch)
    db.commit()
    db.refresh(item)
    return owner, contract, item


def test_deleted_contract_is_hidden_from_history_and_reports(tmp_path):
    db = _session()
    owner, contract, _item = _seed_deleted_contract(
        db,
        deleted_at=datetime.now(timezone.utc),
        storage_path=str(tmp_path / "deleted.enc"),
    )

    assert contracts.list_contracts_history(db=db, user=owner) == []
    assert contracts_metadata(db, department_scope={"法务部"}) == []
    assert report_summary(db, department_scope={"法务部"})["kpi"]["total"] == 0

    try:
        contracts._get_contract(db, contract.id, owner)
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 404
    else:
        raise AssertionError("软删除合同仍可通过详情接口读取")


def test_admin_lists_recoverable_contract_trash(tmp_path):
    db = _session()
    owner, contract, item = _seed_deleted_contract(
        db,
        deleted_at=datetime.now(timezone.utc) - timedelta(days=2),
        storage_path=str(tmp_path / "deleted.enc"),
    )
    administrator = User(
        username="admin",
        password_hash="not-used",
        role="admin",
        department="管理部",
    )
    db.add(administrator)
    db.commit()

    rows = admin.get_contract_trash(db=db, user=administrator)

    assert len(rows) == 1
    assert rows[0].contract_id == contract.id
    assert rows[0].item_id == item.id
    assert rows[0].batch_id == item.batch_id
    assert rows[0].recoverable is True


def test_purge_removes_only_expired_managed_files_and_keeps_tombstone(tmp_path):
    db = _session()
    managed_root = tmp_path / "storage"
    managed_root.mkdir()
    expired_file = managed_root / "expired.enc"
    expired_file.write_bytes(b"encrypted")
    recent_file = managed_root / "recent.enc"
    recent_file.write_bytes(b"encrypted")
    outside_file = tmp_path / "outside.enc"
    outside_file.write_bytes(b"do-not-delete")
    now = datetime.now(timezone.utc)
    _owner, expired, _ = _seed_deleted_contract(
        db,
        deleted_at=now - timedelta(days=31),
        storage_path=str(expired_file),
    )
    _owner, recent, _ = _seed_deleted_contract(
        db,
        deleted_at=now - timedelta(days=2),
        storage_path=str(recent_file),
        username="legal-recent",
    )
    _owner, outside, _ = _seed_deleted_contract(
        db,
        deleted_at=now - timedelta(days=31),
        storage_path=str(outside_file),
        username="legal-outside",
    )

    purged = purge_expired_contract_files(
        db,
        storage_root=str(managed_root),
        retention_days=30,
        now=now,
    )

    assert purged == 1
    assert expired_file.exists() is False
    assert expired.storage_path == ""
    assert expired.status == "purged"
    assert recent_file.exists() is True
    assert recent.storage_path == str(recent_file)
    assert outside_file.exists() is True
    assert outside.storage_path == str(outside_file)
