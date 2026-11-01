"""整改材料上传到合同归属部门，不能借部门参数绕过隔离或幂等身份。"""
from io import BytesIO
from pathlib import Path

import pytest
from fastapi import HTTPException, UploadFile
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.v1.endpoints import contracts
from app.core.config import settings
from app.db.session import Base
from app.models.models import Contract, User


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "STORAGE_DIR", str(tmp_path))
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = User(username="evidence-legal", password_hash="unused", role="legal", department="法务", authorized_departments_json='["采购"]')
        db.add(user)
        db.commit()
        yield db, user, tmp_path
    engine.dispose()


def upload(db, user, department, key="material-test-001"):
    return contracts.upload_contract(
        file=UploadFile(filename="整改凭证.txt", file=BytesIO("双方确认验收合格后付款。".encode())),
        contract_type="采购合同", idempotency_key=key, db=db, user=user, department=department,
    )


def test_upload_to_authorized_source_department(data):
    db, user, _ = data
    result = upload(db, user, "采购")
    assert result.department == "采购"
    assert result.content_sha256
    assert Path(result.storage_path).is_file()


def test_upload_to_foreign_department_rejected_before_storage(data):
    db, user, directory = data
    with pytest.raises(HTTPException) as caught:
        upload(db, user, "人事")
    assert caught.value.status_code == 403
    assert db.query(Contract).count() == 0
    assert list(directory.iterdir()) == []


def test_idempotency_key_cannot_retarget_material_department(data):
    db, user, _ = data
    first = upload(db, user, "采购")
    with pytest.raises(HTTPException) as caught:
        upload(db, user, "法务")
    assert caught.value.status_code == 409
    assert db.query(Contract).count() == 1
    assert db.get(Contract, first.id).department == "采购"


def test_legacy_upload_defaults_to_user_department(data):
    db, user, _ = data
    result = upload(db, user, "")
    assert result.department == "法务"
