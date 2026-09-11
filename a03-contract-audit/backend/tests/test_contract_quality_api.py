from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException
from starlette.requests import Request
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.v1.endpoints import auth, contracts, lookup
from app.core.security import hash_password
from app.db.session import Base
from app.models.models import AuditLog, Contract, LookupItem, User
from app.schemas.contract import LookupItemCreate
from app.schemas.contract import AuditRequest
from app.schemas.contract import ParseErrorResponse
from app.services.parser.extractor import DocumentParseResult
from app.services.parser.ocr import OCRUnavailable
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
            _upload("contract.pdf", b"same contract"),
            contract_type="",
            idempotency_key="upload-request-001",
            db=db,
            user=user,
        )
        repeated = contracts.upload_contract(
            _upload("contract.pdf", b"same contract"),
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
                _upload("contract.pdf", b"different contract"),
                contract_type="",
                idempotency_key="upload-request-001",
                db=db,
                user=user,
            )

        assert exc_info.value.status_code == 409
        assert db.query(Contract).count() == 1
        assert len(list(tmp_path.iterdir())) == 1
    engine.dispose()


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
                _upload("contract.pdf", b"committed contract"),
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
        monkeypatch.setattr(contracts, "extract_elements", lambda _text: {})
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


@pytest.mark.parametrize(
    ("parser_error", "expected_status", "expected_detail"),
    [
        (
            UnicodeError("C:/secret/contracts/private.pdf"),
            422,
            {
                "code": "PDF_TEXT_ENCODING_ERROR",
                "detail": "PDF 文本编码异常，请重新导出 PDF 后重试",
            },
        ),
        (
            OCRUnavailable("C:/secret/models/ocr 不存在"),
            503,
            {
                "code": "OCR_UNAVAILABLE",
                "detail": "OCR 服务暂不可用，请稍后重试或上传含文本层的文件",
            },
        ),
        (
            RuntimeError("C:/secret/internal traceback"),
            500,
            {
                "code": "PARSE_INTERNAL_ERROR",
                "detail": "合同解析失败，请稍后重试",
            },
        ),
        (
            ValueError("C:/secret/programming-defect"),
            500,
            {
                "code": "PARSE_INTERNAL_ERROR",
                "detail": "合同解析失败，请稍后重试",
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
        assert context.value.detail == expected_detail
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
            "detail": "未能从文件中提取有效文本，请上传含文本层的文件",
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
            "extract_elements",
            lambda _text: (_ for _ in ()).throw(RuntimeError("C:/secret/parser")),
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
        {"detail": {"code": "PDF_TEXT_EMPTY", "detail": "安全中文说明"}}
    ).model_dump() == {
        "detail": {"code": "PDF_TEXT_EMPTY", "detail": "安全中文说明"}
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
