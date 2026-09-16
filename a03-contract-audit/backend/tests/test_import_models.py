"""导入批次与合同分类生命周期模型测试。"""

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import Base
from app.models.models import (
    Contract,
    ContractTypeProfile,
    ImportAppendRequest,
    ImportBatch,
    ImportBatchItem,
    LookupItem,
    User,
)


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


def test_import_request_idempotency_is_persisted_and_unique_per_batch():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = User(username="owner", password_hash="x", role="legal", department="法务部")
        db.add(user)
        db.flush()
        batch = ImportBatch(
            owner_id=user.id,
            idempotency_key="create-key",
            request_fingerprint="a" * 64,
        )
        db.add(batch)
        db.flush()
        db.add(ImportAppendRequest(
            batch_id=batch.id,
            idempotency_key="append-key",
            request_fingerprint="b" * 64,
        ))
        db.commit()

        saved = db.get(ImportBatch, batch.id)
        assert saved is not None
        assert saved.request_fingerprint == "a" * 64
        assert saved.department == ""

        db.add(ImportAppendRequest(
            batch_id=batch.id,
            idempotency_key="append-key",
            request_fingerprint="b" * 64,
        ))
        with pytest.raises(IntegrityError):
            db.commit()


def test_contract_type_profile_is_one_to_one_with_lookup_and_cascades():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        lookup = LookupItem(
            category="contract_type",
            value="居间合同",
            sort_order=0,
        )
        lookup.contract_type_profile = ContractTypeProfile(
            aliases_json='["居间协议"]',
            positive_signals_json='["居间服务"]',
            negative_signals_json="[]",
        )
        db.add(lookup)
        db.commit()

        lookup_id = lookup.id
        profile_id = lookup.contract_type_profile.id
        assert lookup.contract_type_profile.version == 1
        assert lookup.contract_type_profile.enabled is True

        db.delete(lookup)
        db.commit()

        assert db.get(LookupItem, lookup_id) is None
        assert db.get(ContractTypeProfile, profile_id) is None


def test_contract_type_profile_rejects_duplicate_lookup_assignment():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        lookup = LookupItem(
            category="contract_type",
            value="居间合同",
            sort_order=0,
        )
        db.add(lookup)
        db.flush()
        db.add_all(
            [
                ContractTypeProfile(lookup_item_id=lookup.id),
                ContractTypeProfile(lookup_item_id=lookup.id),
            ]
        )

        with pytest.raises(IntegrityError):
            db.commit()
