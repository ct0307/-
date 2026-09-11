"""导入批次与合同分类生命周期模型测试。"""

from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.session import Base
from app.models.models import Contract, ImportBatch, ImportBatchItem, User


def test_import_batch_persists_file_level_classification():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = User(username="legal", password_hash="x", role="legal", department="法务部")
        db.add(user)
        db.flush()
        contract = Contract(
            filename="采购合同.pdf",
            storage_path="storage/a.pdf",
            uploaded_by=user.id,
            department="采购中心",
            suggested_type="采购合同",
            type_confidence=0.90,
        )
        batch = ImportBatch(owner_id=user.id, idempotency_key="import-model-1", total=1)
        batch.items.append(
            ImportBatchItem(
                filename=contract.filename,
                contract=contract,
                status="awaiting_confirmation",
            )
        )
        db.add(batch)
        db.commit()

        saved = db.get(ImportBatch, batch.id)
        assert saved is not None
        assert saved.items[0].contract.suggested_type == "采购合同"
        assert saved.items[0].contract.type_confidence == 0.90


def test_contract_soft_delete_fields_are_nullable_and_recoverable():
    deleted_at = datetime.now(timezone.utc)
    contract = Contract(
        filename="draft.pdf",
        storage_path="storage/draft.pdf",
        uploaded_by=1,
        deleted_at=deleted_at,
        deleted_by=1,
    )

    assert contract.deleted_at == deleted_at
    assert contract.deleted_by == 1
