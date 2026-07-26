import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.session import Base
from app.models.models import Contract, Risk
from app.services.audit import runner
from app.services.audit.runner import run_audit
from app.services.parser.extractor import DocumentParseResult


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def _contract(db: Session, name: str) -> Contract:
    contract = Contract(
        filename=name,
        storage_path=f"/{name}",
        department="法务部",
        uploaded_by=1,
    )
    db.add(contract)
    db.commit()
    db.refresh(contract)
    return contract


def test_low_confidence_ocr_requires_review_and_keeps_one_quality_risk(
    monkeypatch, db: Session
):
    contract = _contract(db, "scan.pdf")
    parsed = DocumentParseResult(
        text="有效合同正文" * 60,
        source="ocr",
        ocr_confidence=0.42,
        requires_review=True,
        review_reason="OCR 平均置信度低于 75%",
    )
    monkeypatch.setattr(runner, "extract_document", lambda _path: parsed)
    monkeypatch.setattr(
        runner,
        "audit_contract",
        lambda *_args, **_kwargs: {"risks": [], "cross_checks": []},
    )

    result = run_audit(db, contract)
    run_audit(db, contract)
    db.refresh(contract)
    risks = db.query(Risk).filter(Risk.contract_id == contract.id).all()

    assert contract.status == "review_required"
    assert contract.parse_source == "ocr"
    assert contract.ocr_confidence == 0.42
    assert contract.requires_review is True
    assert result["requires_review"] is True
    assert [risk.category for risk in risks].count("扫描件识别质量不足") == 1
    assert next(risk for risk in risks if risk.category == "扫描件识别质量不足").tier == "red"


def test_native_high_quality_contract_finishes_without_quality_risk(
    monkeypatch, db: Session
):
    contract = _contract(db, "native.txt")
    parsed = DocumentParseResult(text="有效合同正文" * 60, source="native")
    monkeypatch.setattr(runner, "extract_document", lambda _path: parsed)
    monkeypatch.setattr(
        runner,
        "audit_contract",
        lambda *_args, **_kwargs: {"risks": [], "cross_checks": []},
    )

    result = run_audit(db, contract)
    db.refresh(contract)

    assert contract.status == "done"
    assert contract.requires_review is False
    assert result["requires_review"] is False
    assert db.query(Risk).filter(Risk.contract_id == contract.id).count() == 0


def test_short_native_text_requires_review_without_duplicate_parse_risk(
    monkeypatch, db: Session
):
    contract = _contract(db, "short.txt")
    parsed = DocumentParseResult(text="内容残缺", source="native")
    monkeypatch.setattr(runner, "extract_document", lambda _path: parsed)
    monkeypatch.setattr(
        runner,
        "audit_contract",
        lambda *_args, **_kwargs: pytest.fail("短文本不应进入自动审查"),
    )

    result = run_audit(db, contract)
    run_audit(db, contract)
    db.refresh(contract)
    risks = db.query(Risk).filter(Risk.contract_id == contract.id).all()

    assert contract.requires_review is True
    assert contract.review_reason == "合同文本长度不足 200 字"
    assert contract.status == "review_required"
    assert result["requires_review"] is True
    assert [risk.category for risk in risks].count("文本解析失败") == 1
