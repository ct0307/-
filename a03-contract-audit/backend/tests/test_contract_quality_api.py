from datetime import datetime, timezone
from io import BytesIO
import json
from types import SimpleNamespace
from unittest.mock import Mock
from zipfile import ZIP_DEFLATED, ZipFile

import fitz
import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from starlette.requests import Request
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.v1.endpoints import auth, contracts, lookup
from app.core.config import settings
from app.core.security import hash_password
from app.db.session import Base
from app.models.models import (
    AuditLog,
    Contract,
    ContractParseCache,
    ContractTypeProfile,
    LookupItem,
    Risk,
    User,
)
from app.schemas.contract import ContractTypeProfileUpdate, LookupItemCreate
from app.schemas.contract import AuditRequest
from app.schemas.contract import ParseErrorResponse
from app.services.parser.extractor import DocumentBlock, DocumentParseResult, SourceAnchor
from app.services.parser.ocr import OCRError, OCRLimitExceeded, OCRTimeout, OCRUnavailable
from app.services import audit_log


class _CaptureLogger:
    def __init__(self):
        self.events: list[tuple[str, dict]] = []

    def error(self, event: str, **fields) -> None:
        self.events.append((event, fields))


def _create_uploaded_contract(db: Session, tmp_path) -> tuple[User, Contract]:
    user = User(
        username="legal",
        password_hash="hash",
        role="legal",
        department="法务部",
    )
    db.add(user)
    db.flush()
    contract = Contract(
        filename="contract.pdf",
        storage_path=str(tmp_path / "contract.pdf"),
        department=user.department,
        uploaded_by=user.id,
        status="uploaded",
    )
    db.add(contract)
    db.commit()
    return user, contract


def _upload(filename: str, content: bytes) -> object:
    from fastapi import UploadFile

    return UploadFile(filename=filename, file=BytesIO(content))


def _docx_with_invalid_structure() -> bytes:
    content = BytesIO()
    with ZipFile(content, "w", ZIP_DEFLATED) as archive:
        archive.writestr("word/other.xml", "<document />")
    return content.getvalue()


def _encrypted_pdf() -> bytes:
    document = fitz.open()
    document.new_page().insert_text((72, 72), "test")
    try:
        return document.tobytes(
            encryption=fitz.PDF_ENCRYPT_AES_256,
            owner_pw="owner-password",
            user_pw="user-password",
        )
    finally:
        document.close()


def test_risk_api_returns_trace_and_redacts_business_retrieval_query(tmp_path):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        legal, contract = _create_uploaded_contract(db, tmp_path)
        business = User(
            username="business-trace",
            password_hash="hash",
            role="business",
            department=contract.department,
        )
        db.add(business)
        db.add(Risk(
            contract_id=contract.id,
            agent="legal",
            level="medium",
            category="付款期限风险",
            original_text="验收后十日内付款",
            risk_reason="需核验付款条件",
            basis="民法典第五百八十五条",
            suggestion="明确付款期限",
            confidence=88,
            tier="green",
            review_status="pending",
            rag_sources="[]",
            claim_id="C-PAYMENT-001",
            claim_status="accepted",
            source_window_id="window-payment",
            source_clause_ids_json='["第二条"]',
            evidence_ids_json='["LAW-585"]',
            retrieval_attempts_json=(
                '[{"attempt": 1, "query": "付款期限 验收后十日内付款", '
                '"support_status": "supported", "source_ids": ["LAW-585"]}]'
            ),
            contract_evidence_json=(
                '[{"chunk_id": "clause-payment", "clause_id": "第二条", '
                '"anchors": [{"page_number": 2}], "match_type": "exact_quote", '
                '"score": 1.0}]'
            ),
            secondary_review_status="confirmed",
            secondary_review_reason="二次复核确认已有证据支持候选风险",
        ))
        db.commit()

        legal_risk = contracts.get_contract_risks(
            contract.id, db=db, user=legal
        )[0]
        business_risk = contracts.get_contract_risks(
            contract.id, db=db, user=business
        )[0]

        assert legal_risk.claim_id == "C-PAYMENT-001"
        assert legal_risk.evidence_ids == ["LAW-585"]
        assert legal_risk.retrieval_attempts[0]["query"] == "付款期限 验收后十日内付款"
        assert legal_risk.contract_evidence[0]["anchors"][0]["page_number"] == 2
        assert legal_risk.secondary_review_status == "confirmed"
        assert legal_risk.secondary_review_reason == "二次复核确认已有证据支持候选风险"
        assert business_risk["claim_id"] == "C-PAYMENT-001"
        assert business_risk["contract_evidence"][0]["clause_id"] == "第二条"
        assert "query" not in business_risk["retrieval_attempts"][0]
        assert business_risk["secondary_review_status"] == "confirmed"
        assert business_risk["secondary_review_reason"] == "二次复核确认已有证据支持候选风险"

    engine.dispose()


def test_single_upload_is_idempotent_and_rejects_payload_mismatch(monkeypatch, tmp_path):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = User(
            username="upload-idempotency",
            password_hash="hash",
            role="legal",
            department="法务部",
        )
        db.add(user)
        db.commit()
        monkeypatch.setattr(contracts.settings, "STORAGE_DIR", str(tmp_path))

        first = contracts.upload_contract(
            _upload("contract.txt", b"same contract"),
            contract_type="",
            idempotency_key="upload-request-001",
            db=db,
            user=user,
        )
        repeated = contracts.upload_contract(
            _upload("contract.txt", b"same contract"),
            contract_type="",
            idempotency_key="upload-request-001",
            db=db,
            user=user,
        )

        assert repeated.id == first.id
        assert db.query(Contract).count() == 1
        assert len(list(tmp_path.iterdir())) == 1
        assert first.content_sha256 is not None

        with pytest.raises(HTTPException) as exc_info:
            contracts.upload_contract(
                _upload("contract.txt", b"different contract"),
                contract_type="",
                idempotency_key="upload-request-001",
                db=db,
                user=user,
            )

        assert exc_info.value.status_code == 409
        assert db.query(Contract).count() == 1
        assert len(list(tmp_path.iterdir())) == 1
    engine.dispose()


@pytest.mark.parametrize(
    ("filename", "content", "error_code"),
    [
        ("broken.pdf", b"%PDF-not-a-document", "PDF_CORRUPT"),
        ("broken.docx", _docx_with_invalid_structure(), "DOCX_STRUCTURE_INVALID"),
    ],
)
def test_single_upload_rejects_invalid_content_before_persistence(
    monkeypatch, tmp_path, filename, content, error_code
):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = User(
            username=f"invalid-{filename}",
            password_hash="hash",
            role="legal",
            department="法务部",
        )
        db.add(user)
        db.commit()
        monkeypatch.setattr(contracts.settings, "STORAGE_DIR", str(tmp_path))

        with pytest.raises(HTTPException) as raised:
            contracts.upload_contract(
                _upload(filename, content),
                contract_type="",
                idempotency_key=f"invalid-upload-{filename}",
                db=db,
                user=user,
            )

        assert raised.value.status_code == 422
        assert raised.value.detail["code"] == error_code
        assert db.query(Contract).count() == 0
        assert list(tmp_path.iterdir()) == []
    engine.dispose()


@pytest.mark.parametrize(
    ("filename", "content", "status_code", "error_code"),
    [
        ("empty.txt", b"", 400, "EMPTY_FILE"),
        ("disguised.pdf", b"plain text", 400, "FILE_TYPE_MISMATCH"),
        ("encrypted.pdf", _encrypted_pdf(), 422, "PDF_ENCRYPTED"),
    ],
)
def test_single_upload_returns_stable_preflight_error_codes(
    monkeypatch, tmp_path, filename, content, status_code, error_code
):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = User(
            username=f"preflight-{filename}",
            password_hash="hash",
            role="legal",
            department="法务部",
        )
        db.add(user)
        db.commit()
        monkeypatch.setattr(contracts.settings, "STORAGE_DIR", str(tmp_path))

        with pytest.raises(HTTPException) as raised:
            contracts.upload_contract(
                _upload(filename, content),
                contract_type="",
                idempotency_key=f"preflight-upload-{filename}",
                db=db,
                user=user,
            )

        assert raised.value.status_code == status_code
        assert raised.value.detail["code"] == error_code
        assert db.query(Contract).count() == 0
        assert list(tmp_path.iterdir()) == []
    engine.dispose()


def test_legacy_batch_upload_isolates_invalid_content(monkeypatch, tmp_path):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = User(
            username="legacy-invalid-content",
            password_hash="hash",
            role="legal",
            department="法务部",
        )
        db.add(user)
        db.commit()
        monkeypatch.setattr(contracts.settings, "STORAGE_DIR", str(tmp_path))

        result = contracts.batch_upload_contracts(
            files=[_upload("broken.pdf", b"%PDF-not-a-document"), _upload("valid.txt", b"valid")],
            contract_type="采购合同",
            db=db,
            user=user,
        )

        assert result[0] == {
            "filename": "broken.pdf",
            "status": "failed",
            "error_code": "PDF_CORRUPT",
            "error": "PDF 文件损坏或无法打开",
        }
        assert result[1]["filename"] == "valid.txt"
        assert result[1]["status"] == "success"
        assert result[1]["contract_id"] is not None
        assert db.query(Contract).count() == 1
        assert len(list(tmp_path.iterdir())) == 1
    engine.dispose()


def test_legacy_batch_parse_failure_keeps_file_and_processes_next_item(monkeypatch, tmp_path):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = User(username="batch-parse", password_hash="x", role="legal", department="法务部")
        db.add(user)
        db.commit()
        monkeypatch.setattr(contracts.settings, "STORAGE_DIR", str(tmp_path))
        calls = []

        def parse(path):
            calls.append(path)
            if len(calls) == 1:
                raise OCRError("C:/secret/contract.pdf")
            text = "甲方：测试公司\n合同有效条款"
            return DocumentParseResult(
                text, "native", total_pages=1,
                blocks=(DocumentBlock(
                    "pdf-page-1", "page_text", text, SourceAnchor(page_number=1),
                ),),
            )

        monkeypatch.setattr(contracts, "extract_document", parse)
        result = contracts.batch_upload_contracts(
            files=[_upload("broken.txt", b"first"), _upload("good.txt", b"second")],
            contract_type="采购合同", db=db, user=user,
        )
        assert result[0]["error_code"] == "OCR_PROTOCOL_ERROR"
        assert result[0]["status"] == "failed"
        assert "secret" not in repr(result)
        failed = db.get(Contract, result[0]["contract_id"])
        assert failed.status == "failed"
        from pathlib import Path
        assert Path(failed.storage_path).is_file()
        assert result[1]["status"] == "success"
        succeeded = db.get(Contract, result[1]["contract_id"])
        assert succeeded.status == "parsed"
        evidence = json.loads(succeeded.element_evidence_json)
        assert evidence["fields"]["party_a"]["page"] == 1
        assert evidence["document"] == {"total_pages": 1, "missing_pages": []}
    engine.dispose()


def test_parse_response_exposes_missing_pages_and_persists_reason(monkeypatch, tmp_path):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user, contract = _create_uploaded_contract(db, tmp_path)
        parsed = DocumentParseResult(
            "甲方：测试公司", "mixed", requires_review=True,
            review_reason="第 2 页未提取到有效文本", total_pages=3, missing_pages=(2,),
        )
        monkeypatch.setattr(contracts, "extract_document", lambda _: parsed)
        response = contracts.parse_contract(contract.id, db, user)
        assert response.total_pages == 3
        assert response.missing_pages == [2]
        db.expire_all()
        persisted = db.get(Contract, contract.id)
        assert persisted.review_reason == parsed.review_reason
        assert json.loads(persisted.element_evidence_json)["document"] == {
            "total_pages": 3,
            "missing_pages": [2],
        }
        assert response.status == "review_required"
    engine.dispose()


def test_deleted_contract_does_not_block_reupload_with_same_idempotency_key(monkeypatch, tmp_path):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = User(
            username="reupload-after-delete",
            password_hash="hash",
            role="legal",
            department="法务部",
        )
        db.add(user)
        db.flush()
        deleted = Contract(
            filename="deleted.pdf",
            storage_path="",
            department=user.department,
            uploaded_by=user.id,
            upload_idempotency_key="reupload-request-001",
            content_sha256="old-hash",
            deleted_at=datetime.now(timezone.utc),
            status="purged",
        )
        db.add(deleted)
        db.commit()
        monkeypatch.setattr(contracts.settings, "STORAGE_DIR", str(tmp_path))

        uploaded = contracts.upload_contract(
            _upload("contract.txt", b"replacement contract"),
            contract_type="采购合同",
            idempotency_key="reupload-request-001",
            db=db,
            user=user,
        )

        assert uploaded.id != deleted.id
        assert uploaded.deleted_at is None
        assert deleted.upload_idempotency_key is None


def test_upload_keeps_committed_file_when_response_refresh_fails(monkeypatch, tmp_path):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = User(
            username="upload-refresh-failure",
            password_hash="hash",
            role="legal",
            department="法务部",
        )
        db.add(user)
        db.commit()
        monkeypatch.setattr(contracts.settings, "STORAGE_DIR", str(tmp_path))

        def fail_refresh(*args, **kwargs):
            raise RuntimeError("connection lost after commit")

        monkeypatch.setattr(db, "refresh", fail_refresh)
        with pytest.raises(HTTPException) as exc_info:
            contracts.upload_contract(
                _upload("contract.txt", b"committed contract"),
                contract_type="",
                idempotency_key="upload-request-refresh-failure",
                db=db,
                user=user,
            )

        assert exc_info.value.status_code == 500
        assert db.query(Contract).count() == 1
        assert len(list(tmp_path.iterdir())) == 1
    engine.dispose()


def test_legacy_batch_upload_cleans_uncommitted_file_and_hides_internal_error(monkeypatch, tmp_path):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = User(
            username="legacy-batch-failure",
            password_hash="hash",
            role="legal",
            department="法务部",
        )
        db.add(user)
        db.commit()
        monkeypatch.setattr(contracts.settings, "STORAGE_DIR", str(tmp_path))
        monkeypatch.setattr(
            contracts.audit_log,
            "record",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                RuntimeError("postgresql://admin:secret@db.internal/contracts")
            ),
        )

        result = contracts.batch_upload_contracts(
            files=[_upload("contract.txt", "合同正文".encode("utf-8"))],
            contract_type="采购合同",
            db=db,
            user=user,
        )

        assert result == [{
            "filename": "contract.txt",
            "status": "failed",
            "error": "合同上传失败，已回滚",
        }]
        assert db.query(Contract).count() == 0
        assert list(tmp_path.iterdir()) == []
    engine.dispose()


def test_legacy_batch_upload_reports_success_after_commit_when_refresh_fails(monkeypatch, tmp_path):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = User(
            username="legacy-batch-refresh-failure",
            password_hash="hash",
            role="legal",
            department="法务部",
        )
        db.add(user)
        db.commit()
        monkeypatch.setattr(contracts.settings, "STORAGE_DIR", str(tmp_path))
        monkeypatch.setattr(
            db,
            "refresh",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                RuntimeError("connection lost after commit")
            ),
        )

        result = contracts.batch_upload_contracts(
            files=[_upload("contract.txt", "合同正文".encode("utf-8"))],
            contract_type="采购合同",
            db=db,
            user=user,
        )

        saved = db.query(Contract).one()
        assert result == [{
            "filename": "contract.txt",
            "status": "success",
            "contract_id": saved.id,
            "warning": "合同已上传，但响应确认失败",
        }]
        assert len(list(tmp_path.iterdir())) == 1
    engine.dispose()


def test_audit_log_record_does_not_own_the_transaction():
    db = Mock()

    audit_log.record(db, user_id=7, action="upload", target="contract:1")

    db.add.assert_called_once()
    db.flush.assert_called_once()
    db.commit.assert_not_called()


def test_login_commits_audit_log_before_request_session_closes():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(User(
            username="audit-login",
            password_hash=hash_password("secret123"),
            role="legal",
            department="legal",
        ))
        db.commit()

        request = Request({
            "type": "http",
            "method": "POST",
            "path": "/api/v1/auth/login",
            "headers": [],
            "client": ("127.0.0.1", 12345),
        })
        auth.login(
            request=request,
            form=SimpleNamespace(username="audit-login", password="secret123"),
            db=db,
        )

    with Session(engine) as db:
        assert db.query(AuditLog).filter(AuditLog.action == "login").count() == 1
    engine.dispose()


def test_lookup_write_rolls_back_when_audit_log_fails(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = User(
            username="audit-admin",
            password_hash="hash",
            role="admin",
            department="admin",
        )
        db.add(user)
        db.commit()

        def fail_record(*args, **kwargs):
            raise RuntimeError("audit storage unavailable")

        monkeypatch.setattr(lookup.audit_log, "record", fail_record)
        with pytest.raises(RuntimeError, match="audit storage unavailable"):
            lookup.create_lookup(
                LookupItemCreate(
                    category="department",
                    value="研发部",
                    sort_order=1,
                ),
                db=db,
                current_user=user,
            )

    with Session(engine) as db:
        assert db.query(LookupItem).count() == 0
    engine.dispose()


def test_admin_can_list_and_update_contract_type_profile_with_redacted_audit():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        admin = User(
            username="profile-admin",
            password_hash="hash",
            role="admin",
            department="管理",
        )
        item = LookupItem(category="contract_type", value="采购合同", sort_order=0)
        item.contract_type_profile = ContractTypeProfile(
            aliases_json='["采购"]',
            positive_signals_json='["供货"]',
            negative_signals_json="[]",
            version=3,
        )
        db.add_all((admin, item))
        db.commit()

        listed = lookup.list_contract_type_profiles(db=db, current_user=admin)
        assert len(listed) == 1
        assert listed[0].value == "采购合同"
        assert listed[0].version == 3

        updated = lookup.update_contract_type_profile(
            item.id,
            ContractTypeProfileUpdate(
                aliases=[" 采购 ", "采购", ""],
                positive_signals=["供货", "敏感合同正文片段"],
                negative_signals=["采购清单"],
                enabled=True,
                version=3,
            ),
            db=db,
            current_user=admin,
        )

        assert updated.aliases == ["采购"]
        assert updated.version == 4
        entry = db.query(AuditLog).filter_by(
            action="contract_type_profile_update"
        ).one()
        assert entry.target == f"lookup:{item.id}"
        assert "敏感合同正文片段" not in entry.detail
        assert '"positive_signals_count":2' in entry.detail
    engine.dispose()


def test_non_admin_cannot_read_or_write_contract_type_profiles():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        legal = User(
            username="profile-legal",
            password_hash="hash",
            role="legal",
            department="法务部",
        )
        db.add(legal)
        db.commit()

        with pytest.raises(HTTPException) as list_error:
            lookup.list_contract_type_profiles(db=db, current_user=legal)
        assert list_error.value.status_code == 403

        with pytest.raises(HTTPException) as update_error:
            lookup.update_contract_type_profile(
                1,
                ContractTypeProfileUpdate(enabled=True, version=1),
                db=db,
                current_user=legal,
            )
        assert update_error.value.status_code == 403
    engine.dispose()


def test_type_profile_update_rejects_department_lookup_and_stale_version():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        admin = User(
            username="profile-owner",
            password_hash="hash",
            role="admin",
            department="管理",
        )
        department = LookupItem(category="department", value="采购中心", sort_order=0)
        contract_type = LookupItem(
            category="contract_type",
            value="采购合同",
            sort_order=0,
        )
        contract_type.contract_type_profile = ContractTypeProfile(version=2)
        db.add_all((admin, department, contract_type))
        db.commit()

        with pytest.raises(HTTPException) as wrong_category:
            lookup.update_contract_type_profile(
                department.id,
                ContractTypeProfileUpdate(enabled=True, version=1),
                db=db,
                current_user=admin,
            )
        assert wrong_category.value.status_code == 404

        with pytest.raises(HTTPException) as conflict:
            lookup.update_contract_type_profile(
                contract_type.id,
                ContractTypeProfileUpdate(enabled=True, version=1),
                db=db,
                current_user=admin,
            )
        assert conflict.value.status_code == 409
        assert contract_type.contract_type_profile.version == 2
    engine.dispose()


def test_type_profile_update_schema_rejects_extra_and_oversized_arrays():
    with pytest.raises(ValidationError):
        ContractTypeProfileUpdate(
            aliases=[str(index) for index in range(33)],
            enabled=True,
            version=1,
        )
    with pytest.raises(ValidationError):
        ContractTypeProfileUpdate.model_validate(
            {"enabled": True, "version": 1, "unexpected": "value"}
        )


def test_type_profile_update_rejects_oversized_term_with_422():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        admin = User(
            username="profile-length-admin",
            password_hash="hash",
            role="admin",
            department="管理",
        )
        item = LookupItem(category="contract_type", value="采购合同", sort_order=0)
        item.contract_type_profile = ContractTypeProfile()
        db.add_all((admin, item))
        db.commit()

        with pytest.raises(HTTPException) as error:
            lookup.update_contract_type_profile(
                item.id,
                ContractTypeProfileUpdate(
                    aliases=["超" * 65],
                    enabled=True,
                    version=1,
                ),
                db=db,
                current_user=admin,
            )
        assert error.value.status_code == 422
    engine.dispose()


def test_contract_type_lookup_create_initializes_empty_profile():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        admin = User(
            username="profile-create-admin",
            password_hash="hash",
            role="admin",
            department="管理",
        )
        db.add(admin)
        db.commit()

        created = lookup.create_lookup(
            LookupItemCreate(
                category="contract_type",
                value="居间合同",
                sort_order=20,
            ),
            db=db,
            current_user=admin,
        )

        profile = db.query(ContractTypeProfile).filter_by(
            lookup_item_id=created.id
        ).one()
        assert profile.aliases_json == "[]"
        assert profile.version == 1
    engine.dispose()


def test_history_status_prioritizes_manual_review():
    contract = Contract(
        filename="scan.pdf",
        storage_path="/scan.pdf",
        department="法务部",
        uploaded_by=1,
        status="review_required",
    )

    assert contracts._derive_status(contract, []) == "待人工复核"


def test_history_status_marks_parse_failure_instead_of_compliant():
    contract = Contract(
        filename="failed.pdf",
        storage_path="/tmp/failed.pdf",
        contract_type="采购合同",
        status="failed",
        department="法务部",
        uploaded_by=1,
    )

    assert contracts._derive_status(contract, []) == "解析失败"


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
        monkeypatch.setattr(
            contracts,
            "extract_elements_with_llm",
            lambda _text: pytest.fail("同步解析端点不得调用大模型"),
            raising=False,
        )

        response = contracts.parse_contract(contract.id, db=db, user=user)

        db.refresh(contract)
        assert response.requires_review is True
        assert response.ocr_confidence == 0.42
        assert contract.requires_review is True
        assert contract.review_reason == "OCR 平均置信度低于 75%"
    engine.dispose()


def test_parse_cache_reuses_synchronous_parse_during_audit(monkeypatch, tmp_path):
    from app.services.audit import runner as audit_runner

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    parsed = DocumentParseResult(text="有效合同正文" * 60, source="native")
    with Session(engine) as db:
        user, contract = _create_uploaded_contract(db, tmp_path)
        contract.content_sha256 = "a" * 64
        db.commit()
        monkeypatch.setattr(contracts, "extract_document", lambda _path: parsed)

        contracts.parse_contract(contract.id, db=db, user=user)

        assert db.query(ContractParseCache).filter_by(
            contract_id=contract.id
        ).count() == 1
        monkeypatch.setattr(
            audit_runner,
            "extract_document",
            lambda _path: pytest.fail("审查不应重复解析已有缓存的合同"),
        )
        monkeypatch.setattr(
            audit_runner,
            "audit_contract",
            lambda *_args, **_kwargs: {
                "risks": [],
                "cross_checks": [],
                "issues": [],
                "coverage": {"planned": 1, "completed": 1},
            },
        )

        result = audit_runner.run_audit(db, contract)

        assert result["status"] == "done"
    engine.dispose()


def test_parse_cache_reuses_legacy_batch_upload_parse_during_audit(
    monkeypatch,
    tmp_path,
):
    from app.services.audit import runner as audit_runner

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    parsed = DocumentParseResult(text="批量合同正文" * 60, source="native")
    with Session(engine) as db:
        user = User(
            username="batch-cache-legal",
            password_hash="hash",
            role="legal",
            department="法务部",
        )
        db.add(user)
        db.commit()
        monkeypatch.setattr(settings, "STORAGE_DIR", str(tmp_path))
        monkeypatch.setattr(contracts, "extract_document", lambda _path: parsed)

        uploaded = contracts.batch_upload_contracts(
            files=[_upload("batch.txt", "批量合同正文".encode("utf-8"))],
            contract_type="服务合同",
            db=db,
            user=user,
        )
        contract = db.get(Contract, uploaded[0]["contract_id"])

        assert contract.content_sha256 is not None
        assert db.query(ContractParseCache).filter_by(
            contract_id=contract.id
        ).count() == 1
        monkeypatch.setattr(
            audit_runner,
            "extract_document",
            lambda _path: pytest.fail("审查不应重复解析批量上传合同"),
        )
        monkeypatch.setattr(
            audit_runner,
            "audit_contract",
            lambda *_args, **_kwargs: {
                "risks": [],
                "cross_checks": [],
                "issues": [],
                "coverage": {"planned": 1, "completed": 1},
            },
        )

        result = audit_runner.run_audit(db, contract)

        assert result["status"] == "done"
    engine.dispose()


@pytest.mark.parametrize(
    ("parser_error", "expected_status", "expected_detail"),
    [
        (
            UnicodeError("C:/secret/contracts/private.pdf"),
            422,
            {
                "code": "PDF_TEXT_ENCODING_ERROR",
                "detail": "PDF 文本编码异常，请重新导出 PDF 后重试",
                "action": "重新导出 PDF 后重试",
            },
        ),
        (
            OCRUnavailable("C:/secret/models/ocr 不存在"),
            503,
            {
                "code": "OCR_UNAVAILABLE",
                "detail": "OCR 服务暂不可用，请联系管理员修复后重试",
                "action": "联系管理员修复后重试",
            },
        ),
        (
            OCRTimeout("C:/secret/contracts/timeout.pdf"),
            503,
            {
                "code": "OCR_TIMEOUT",
                "detail": "OCR 处理超时，请稍后重试或拆分文件",
                "action": "稍后重试或拆分文件",
            },
        ),
        (
            OCRLimitExceeded("C:/secret/contracts/large.pdf"),
            422,
            {
                "code": "OCR_LIMIT_EXCEEDED",
                "detail": "文件超出 OCR 处理限制，请拆分或压缩文件后重试",
                "action": "拆分或压缩文件后重试",
            },
        ),
        (
            OCRError("C:/secret/third-party-error"),
            503,
            {
                "code": "OCR_PROTOCOL_ERROR",
                "detail": "OCR 服务响应异常，请稍后重试",
                "action": "稍后重试",
            },
        ),
        (
            RuntimeError("C:/secret/internal traceback"),
            500,
            {
                "code": "PARSE_INTERNAL_ERROR",
                "detail": "合同解析失败，请稍后重试",
                "action": "稍后重试",
            },
        ),
        (
            ValueError("C:/secret/programming-defect"),
            500,
            {
                "code": "PARSE_INTERNAL_ERROR",
                "detail": "合同解析失败，请稍后重试",
                "action": "稍后重试",
            },
        ),
    ],
)
def test_parse_contract_maps_exceptions_to_safe_errors(
    monkeypatch,
    tmp_path,
    parser_error,
    expected_status,
    expected_detail,
):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user, contract = _create_uploaded_contract(db, tmp_path)
        logger = _CaptureLogger()
        monkeypatch.setattr(contracts, "log", logger, raising=False)

        def raise_parser_error(_path):
            raise parser_error

        monkeypatch.setattr(contracts, "extract_document", raise_parser_error)

        with pytest.raises(HTTPException) as context:
            contracts.parse_contract(contract.id, db=db, user=user)

        assert context.value.status_code == expected_status
        assert context.value.detail == {
            **expected_detail,
            "correlation_id": f"contract:{contract.id}",
        }
        assert "secret" not in repr(context.value.detail).lower()
        assert logger.events == [
            (
                "contract.parse_failed",
                {
                    "contract_id": contract.id,
                    "code": expected_detail["code"],
                    "exception_type": type(parser_error).__name__,
                },
            )
        ]
        assert "secret" not in repr(logger.events).lower()
    engine.dispose()


def test_parse_contract_rejects_empty_text_with_safe_error(monkeypatch, tmp_path):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user, contract = _create_uploaded_contract(db, tmp_path)
        logger = _CaptureLogger()
        monkeypatch.setattr(contracts, "log", logger, raising=False)
        monkeypatch.setattr(
            contracts,
            "extract_document",
            lambda _path: DocumentParseResult("  \n", "native"),
        )

        with pytest.raises(HTTPException) as context:
            contracts.parse_contract(contract.id, db=db, user=user)

        assert context.value.status_code == 422
        assert context.value.detail == {
            "code": "PDF_TEXT_EMPTY",
            "detail": "未能从文件中提取有效文本，请重新导出 PDF 后重试",
            "action": "重新导出 PDF 后重试",
            "correlation_id": f"contract:{contract.id}",
        }
        assert logger.events[0][1]["exception_type"] == "ValueError"
    engine.dispose()


def test_parse_contract_rolls_back_partial_quality_changes(monkeypatch, tmp_path):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user, contract = _create_uploaded_contract(db, tmp_path)
        monkeypatch.setattr(contracts, "log", _CaptureLogger(), raising=False)
        monkeypatch.setattr(
            contracts,
            "extract_document",
            lambda _path: DocumentParseResult(
                "有效文本" * 30,
                "ocr",
                0.31,
                True,
                "OCR 质量低",
            ),
        )
        monkeypatch.setattr(
            contracts,
            "extract_element_result",
            lambda _parsed: (_ for _ in ()).throw(RuntimeError("C:/secret/parser")),
        )

        with pytest.raises(HTTPException):
            contracts.parse_contract(contract.id, db=db, user=user)

        db.expire_all()
        persisted = db.get(Contract, contract.id)
        assert persisted.status == "uploaded"
        assert persisted.requires_review is False
        assert persisted.ocr_confidence is None
        assert persisted.review_reason is None
    engine.dispose()


def test_parse_contract_documents_safe_error_envelope():
    parse_route = next(
        route for route in contracts.router.routes
        if getattr(route, "endpoint", None) is contracts.parse_contract
    )

    assert {
        status_code: parse_route.responses[status_code]["model"]
        for status_code in (422, 503, 500)
    } == {
        422: ParseErrorResponse,
        503: ParseErrorResponse,
        500: ParseErrorResponse,
    }
    assert ParseErrorResponse.model_validate(
        {
            "detail": {
                "code": "PDF_TEXT_EMPTY",
                "detail": "安全中文说明",
                "action": "重新导出 PDF 后重试",
                "correlation_id": "contract:1",
            }
        }
    ).model_dump() == {
        "detail": {
            "code": "PDF_TEXT_EMPTY",
            "detail": "安全中文说明",
            "action": "重新导出 PDF 后重试",
            "correlation_id": "contract:1",
        }
    }


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
