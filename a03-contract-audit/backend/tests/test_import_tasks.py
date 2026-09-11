"""导入解析任务测试。"""

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.crypto import encrypt_bytes
from app.db.session import Base
from app.models.models import Contract, ImportBatch, ImportBatchItem, LookupItem, User
from app.tasks import import_tasks


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


def test_parse_import_item_persists_type_suggestion(monkeypatch, tmp_path):
    engine = _db()
    with Session(engine) as db:
        user = User(username="legal", password_hash="x", role="legal", department="法务部")
        db.add(user)
        db.flush()
        path = tmp_path / "purchase.txt"
        path.write_bytes(encrypt_bytes("采购服务器设备，乙方负责供货和验收。".encode("utf-8")))
        contract = Contract(
            filename="采购合同.txt",
            storage_path=str(path),
            uploaded_by=user.id,
            department=user.department,
        )
        batch = ImportBatch(owner_id=user.id, idempotency_key="task-success", total=1)
        batch.items.append(ImportBatchItem(filename=contract.filename, contract=contract, status="queued"))
        db.add(batch)
        db.add(LookupItem(category="contract_type", value="采购合同"))
        db.commit()
        item_id = batch.items[0].id

    monkeypatch.setattr(import_tasks, "SessionLocal", lambda: Session(engine))
    result = import_tasks.parse_import_item.run(item_id)

    with Session(engine) as db:
        item = db.get(ImportBatchItem, item_id)
        assert result["status"] == "ready"
        assert item.status == "ready"
        assert item.contract.status == "parsed"
        assert item.contract.suggested_type == "采购合同"
        assert item.contract.contract_type == "采购合同"
        assert item.contract.type_confirmed_at is None


def test_parse_import_item_hides_parser_failure_details(monkeypatch, tmp_path):
    engine = _db()
    with Session(engine) as db:
        user = User(username="legal", password_hash="x", role="legal", department="法务部")
        db.add(user)
        db.flush()
        contract = Contract(
            filename="bad.pdf",
            storage_path=str(tmp_path / "missing.pdf"),
            uploaded_by=user.id,
            department=user.department,
        )
        batch = ImportBatch(owner_id=user.id, idempotency_key="task-failure", total=1)
        batch.items.append(ImportBatchItem(filename=contract.filename, contract=contract, status="queued"))
        db.add(batch)
        db.commit()
        item_id = batch.items[0].id

    monkeypatch.setattr(import_tasks, "SessionLocal", lambda: Session(engine))
    result = import_tasks.parse_import_item.run(item_id)

    with Session(engine) as db:
        item = db.get(ImportBatchItem, item_id)
        assert result["status"] == "failed"
        assert item.status == "failed"
        assert item.error_code == "PARSE_FAILED"
        assert item.error_message == "合同解析失败，请重新解析或删除草稿"
        assert "missing.pdf" not in item.error_message
