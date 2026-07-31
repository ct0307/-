import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.v1.endpoints import contracts
from app.db.session import Base
from app.models.models import Contract, User
from app.schemas.contract import AuditRequest
from app.services.parser.extractor import DocumentParseResult


def test_history_status_prioritizes_manual_review():
    contract = Contract(
        filename="scan.pdf",
        storage_path="/scan.pdf",
        department="法务部",
        uploaded_by=1,
        status="review_required",
    )

    assert contracts._derive_status(contract, []) == "待人工复核"


def test_parse_response_persists_ocr_quality(monkeypatch, tmp_path):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = User(
            username="legal",
            password_hash="hash",
            role="legal",
            department="法务部",
        )
        db.add(user)
        db.flush()
        contract = Contract(
            filename="scan.pdf",
            storage_path=str(tmp_path / "scan.pdf"),
            department=user.department,
            uploaded_by=user.id,
        )
        db.add(contract)
        db.commit()
        monkeypatch.setattr(
            contracts,
            "extract_document",
            lambda _path: DocumentParseResult(
                "有效文本" * 60,
                "ocr",
                0.42,
                True,
                "OCR 平均置信度低于 75%",
            ),
        )
        monkeypatch.setattr(contracts, "extract_elements_with_llm", lambda _text: {})

        response = contracts.parse_contract(contract.id, db=db, user=user)

        db.refresh(contract)
        assert response.requires_review is True
        assert response.ocr_confidence == 0.42
        assert contract.requires_review is True
        assert contract.review_reason == "OCR 平均置信度低于 75%"
    engine.dispose()


def test_audit_rejects_contract_without_confirmed_type(monkeypatch, tmp_path):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = User(
            username="legal-auditor",
            password_hash="hash",
            role="legal",
            department="法务部",
        )
        db.add(user)
        db.flush()
        contract = Contract(
            filename="purchase.txt",
            storage_path=str(tmp_path / "purchase.txt"),
            contract_type="",
            department=user.department,
            uploaded_by=user.id,
            status="parsed",
        )
        db.add(contract)
        db.commit()
        monkeypatch.setattr(
            contracts,
            "run_audit",
            lambda *_args, **_kwargs: pytest.fail("空合同类型不得启动审查"),
        )

        with pytest.raises(HTTPException) as context:
            contracts.audit_contract_endpoint(
                contract.id,
                AuditRequest(dimensions=[]),
                db=db,
                user=user,
            )

        assert context.value.status_code == 422
    engine.dispose()
