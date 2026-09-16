"""导入解析任务测试。"""

from io import BytesIO

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.crypto import encrypt_bytes
from app.db.session import Base
from app.models.models import (
    Contract,
    ContractTypeProfile,
    ImportBatch,
    ImportBatchItem,
    LookupItem,
    User,
)
from app.services.parser.ocr import OCRUnavailable
from app.services.imports.classifier import TypeSuggestion
from app.services.parser.elements import ElementResult
from app.tasks import import_tasks


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


def _image_only_docx_bytes() -> bytes:
    from docx import Document
    from docx.shared import Inches
    from PIL import Image

    image_stream = BytesIO()
    Image.new("RGB", (1600, 2200), "white").save(image_stream, format="PNG")
    image_stream.seek(0)
    document = Document()
    document.add_picture(image_stream, width=Inches(6))
    output = BytesIO()
    document.save(output)
    return output.getvalue()


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
        assert result["status"] == "awaiting_confirmation"
        assert item.status == "awaiting_confirmation"
        assert item.contract.status == "parsed"
        assert item.contract.suggested_type == "采购合同"
        assert item.contract.contract_type == "采购合同"
        assert item.contract.type_confirmed_at is None


def test_parse_import_item_round_trips_gb18030_text_without_loss(monkeypatch, tmp_path):
    engine = _db()
    source = "合同类型：采购合同\n甲方向乙方采购设备并约定验收。"
    captured: dict[str, str] = {}
    with Session(engine) as db:
        user = User(
            username="gb18030-legal",
            password_hash="x",
            role="legal",
            department="法务部",
        )
        db.add(user)
        db.flush()
        path = tmp_path / "gb18030.txt"
        path.write_bytes(encrypt_bytes(source.encode("gb18030")))
        contract = Contract(
            filename="采购合同.txt",
            storage_path=str(path),
            uploaded_by=user.id,
            department=user.department,
        )
        batch = ImportBatch(
            owner_id=user.id,
            idempotency_key="gb18030-task",
            total=1,
        )
        batch.items.append(
            ImportBatchItem(filename=contract.filename, contract=contract, status="queued")
        )
        lookup = LookupItem(category="contract_type", value="采购合同")
        lookup.contract_type_profile = ContractTypeProfile(
            aliases_json='["采购"]',
            positive_signals_json='["采购", "设备"]',
            negative_signals_json="[]",
        )
        db.add_all([batch, lookup])
        db.commit()
        item_id = batch.items[0].id

    def capture_elements(parsed):
        captured["text"] = parsed.text
        return ElementResult({}, {}, (), parsed.text)

    monkeypatch.setattr(import_tasks, "SessionLocal", lambda: Session(engine))
    monkeypatch.setattr(import_tasks, "extract_element_result", capture_elements)

    result = import_tasks.parse_import_item.run(item_id)

    with Session(engine) as db:
        item = db.get(ImportBatchItem, item_id)
        assert result["status"] == "awaiting_confirmation"
        assert captured["text"] == source
        assert item.contract.suggested_type == "采购合同"


def test_parse_import_item_passes_classification_and_parse_review_gates(monkeypatch, tmp_path):
    engine = _db()
    with Session(engine) as db:
        user = User(username="review-legal", password_hash="x", role="legal", department="法务部")
        db.add(user)
        db.flush()
        contract = Contract(filename="采购合同.txt", storage_path=str(tmp_path / "sample.txt"), uploaded_by=user.id, department=user.department)
        batch = ImportBatch(owner_id=user.id, idempotency_key="task-review-gates", total=1)
        batch.items.append(ImportBatchItem(filename=contract.filename, contract=contract, status="queued"))
        db.add(batch)
        db.add(LookupItem(category="contract_type", value="采购合同"))
        db.commit()
        item_id = batch.items[0].id

    class Parsed:
        text = "采购设备并交付"
        requires_review = True
        review_reason = "OCR 质量低"

    captured = {}
    monkeypatch.setattr(import_tasks, "SessionLocal", lambda: Session(engine))
    monkeypatch.setattr(import_tasks, "extract_document", lambda _: Parsed())
    monkeypatch.setattr(import_tasks, "apply_parse_quality", lambda _contract, _parsed: None)
    monkeypatch.setattr(import_tasks, "classify_contract_type", lambda **_: TypeSuggestion("采购合同", 0.99, ["采购"], auto_ready_eligible=True))
    monkeypatch.setattr(
        import_tasks,
        "extract_element_result",
        lambda parsed: ElementResult({}, {}, (), parsed.text),
    )
    original_target_status = import_tasks.target_status

    def capture_status(*args, **kwargs):
        captured.update(kwargs)
        return original_target_status(*args, **kwargs)

    monkeypatch.setattr(import_tasks, "target_status", capture_status)
    result = import_tasks.parse_import_item.run(item_id)

    assert result["status"] == "awaiting_confirmation"
    assert captured["auto_ready_eligible"] is True
    assert captured["requires_review"] is True


def test_parse_import_item_keeps_image_only_docx_awaiting_confirmation(
    monkeypatch,
    tmp_path,
):
    engine = _db()
    with Session(engine) as db:
        user = User(
            username="image-review-legal",
            password_hash="x",
            role="legal",
            department="法务部",
        )
        db.add(user)
        db.flush()
        path = tmp_path / "image-only.docx"
        path.write_bytes(encrypt_bytes(_image_only_docx_bytes()))
        contract = Contract(
            filename="采购合同.docx",
            storage_path=str(path),
            uploaded_by=user.id,
            department=user.department,
        )
        batch = ImportBatch(
            owner_id=user.id,
            idempotency_key="task-image-docx-review",
            total=1,
        )
        batch.items.append(
            ImportBatchItem(filename=contract.filename, contract=contract, status="queued")
        )
        db.add(batch)
        lookup = LookupItem(category="contract_type", value="采购合同")
        lookup.contract_type_profile = ContractTypeProfile(
            aliases_json='["采购", "购置"]',
            positive_signals_json='["采购", "供货", "设备"]',
            negative_signals_json="[]",
        )
        db.add(lookup)
        db.commit()
        item_id = batch.items[0].id

    monkeypatch.setattr(import_tasks, "SessionLocal", lambda: Session(engine))
    monkeypatch.setattr(
        import_tasks,
        "classify_contract_type",
        lambda **_: TypeSuggestion(
            "采购合同",
            0.99,
            ["filename:采购合同"],
            auto_ready_eligible=True,
        ),
    )

    result = import_tasks.parse_import_item.run(item_id)

    with Session(engine) as db:
        item = db.get(ImportBatchItem, item_id)
        assert result["status"] == "awaiting_confirmation"
        assert item.status == "awaiting_confirmation"
        assert item.contract.requires_review is True
        assert item.contract.review_reason == "DOCX 疑似图片型文档，未提取到足够正文"


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
        assert item.error_code == "PARSE_INTERNAL_ERROR"
        assert item.error_message == "合同解析失败，请稍后重试"
        assert "missing.pdf" not in item.error_message


def test_parse_import_item_persists_ocr_unavailable_code_and_whitelisted_log_fields(monkeypatch, tmp_path):
    engine = _db()
    with Session(engine) as db:
        user = User(username="ocr-legal", password_hash="x", role="legal", department="法务部")
        db.add(user)
        db.flush()
        contract = Contract(
            filename="scan.pdf",
            storage_path=str(tmp_path / "private.pdf"),
            uploaded_by=user.id,
            department=user.department,
        )
        batch = ImportBatch(owner_id=user.id, idempotency_key="task-ocr-unavailable", total=1)
        batch.items.append(ImportBatchItem(filename=contract.filename, contract=contract, status="queued"))
        db.add(batch)
        db.commit()
        item_id = batch.items[0].id

    class CaptureLogger:
        def __init__(self):
            self.events = []

        def error(self, event, **fields):
            self.events.append((event, fields))

    logger = CaptureLogger()
    monkeypatch.setattr(import_tasks, "SessionLocal", lambda: Session(engine))
    monkeypatch.setattr(
        import_tasks,
        "extract_document",
        lambda _path: (_ for _ in ()).throw(OCRUnavailable("C:/secret/models/private.pdf")),
    )
    monkeypatch.setattr(import_tasks, "log", logger, raising=False)

    result = import_tasks.parse_import_item.run(item_id)

    with Session(engine) as db:
        item = db.get(ImportBatchItem, item_id)
        assert result["status"] == "failed"
        assert item.error_code == "OCR_UNAVAILABLE"
        assert item.error_message == "OCR 服务暂不可用，请联系管理员修复后重试"
        assert logger.events == [
            (
                "import.parse_failed",
                {
                    "item_id": item_id,
                    "contract_id": item.contract_id,
                    "code": "OCR_UNAVAILABLE",
                    "exception_type": "OCRUnavailable",
                    "attempts": 1,
                },
            )
        ]
        assert "secret" not in repr(logger.events).lower()
