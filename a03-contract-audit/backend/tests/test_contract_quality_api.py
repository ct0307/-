import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.v1.endpoints import contracts
from app.db.session import Base
from app.models.models import Contract, User
from app.schemas.contract import AuditRequest
from app.schemas.contract import ParseErrorResponse
from app.services.parser.extractor import DocumentParseResult
from app.services.parser.ocr import OCRUnavailable


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
            "extract_elements_with_llm",
            lambda _text: (_ for _ in ()).throw(RuntimeError("C:/secret/llm")),
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
