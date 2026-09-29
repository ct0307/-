"""使用真实 SQLite 查询验证权限边界，避免伪查询绕过过滤。"""
from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from pydantic import ValidationError

from app.db.session import Base
from app.models.models import Contract, Risk, User, Rectification
from app.api.v1.endpoints import rectifications, chat, risks as risk_endpoint
from app.schemas.contract import RectificationCreate, RectificationStatusUpdate, RiskStatusUpdate


@pytest.fixture
def data(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    monkeypatch.setattr(rectifications.audit_log, "record", lambda *a, **k: None)
    with Session(engine) as db:
        legal = User(username="legal", password_hash="x", role="legal", department="采购")
        db.add(legal)
        db.flush()
        risks = []
        for department in ("采购", "财务"):
            contract = Contract(filename=f"{department}.txt", storage_path="unused", department=department, uploaded_by=legal.id)
            db.add(contract)
            db.flush()
            risk = Risk(contract_id=contract.id, category="付款风险", level="high", original_text="原文", basis="未核验依据", suggestion="待核验", review_status="confirmed")
            db.add(risk)
            db.flush()
            db.add(Rectification(contract=contract.filename, risk=risk.category, risk_id=risk.id, level="high", owner="legal", created="2026-09-29", due="2026-10-06", status="处理中"))
            risks.append(risk)
        db.add(Rectification(contract="历史无归属", risk="旧风险", level="high", created="2026-09-29", due="2026-10-06"))
        db.commit()
        yield db, legal, risks
    engine.dispose()


def test_rectification_list_filters_department_and_orphans(data):
    db, user, _ = data
    rows = rectifications.list_rectifications(db, user)
    assert len(rows) == 1
    assert rows[0].contract == "采购.txt"


def test_rectification_update_rejects_other_department(data):
    db, user, _ = data
    with pytest.raises(HTTPException) as caught:
        rectifications.update_rectification_status("RC002", RectificationStatusUpdate(status="待复核", resolution="越权修改"), db, user)
    assert caught.value.status_code == 403


def test_rectification_create_rejects_foreign_risk(data):
    db, user, risks = data
    with pytest.raises(HTTPException) as caught:
        rectifications.create_rectification(RectificationCreate(contract="伪造", risk="伪造", risk_id=risks[1].id), db, user)
    assert caught.value.status_code == 403


def test_rectification_create_uses_server_labels(data):
    db, user, risks = data
    result = rectifications.create_rectification(RectificationCreate(contract="伪造", risk="伪造", risk_id=risks[0].id), db, user)
    assert result.contract == "采购.txt"
    assert result.risk == "付款风险"


def test_chat_rejects_client_supplied_authority():
    with pytest.raises(ValidationError):
        chat.ChatRequest(risk_id=1, message="说明", risk_context={"category": "伪造", "basis": "任意法规"})


def test_chat_rejects_cross_department_before_model(data, monkeypatch):
    db, user, risks = data
    monkeypatch.setattr(chat, "get_llm_adapter", lambda: pytest.fail("越权请求不能调用模型"))
    with pytest.raises(HTTPException) as caught:
        chat.chat_with_risk(chat.ChatRequest(risk_id=risks[1].id, message="解释"), db, user)
    assert caught.value.status_code == 403


def test_chat_unverified_evidence_is_explicit_degradation(data, monkeypatch):
    db, user, risks = data
    monkeypatch.setattr(chat, "get_llm_adapter", lambda: pytest.fail("缺少已验证依据时不得生成法律引用"))
    response = chat.chat_with_risk(chat.ChatRequest(risk_id=risks[0].id, message="法律依据是什么"), db, user)
    assert response.state == "EVIDENCE_UNVERIFIED"
    assert response.references == []


def test_risk_review_requires_comment_and_preserves_parse_review_flag(data, monkeypatch):
    db, user, risks = data
    contract = db.get(Contract, risks[0].contract_id)
    contract.requires_review = True
    db.commit()
    with pytest.raises(HTTPException) as caught:
        risk_endpoint.update_risk_status(risks[0].id, RiskStatusUpdate(review_status="confirmed"), db, user)
    assert caught.value.status_code == 422
    result = risk_endpoint.update_risk_status(
        risks[0].id,
        RiskStatusUpdate(review_status="confirmed", review_comment="已核对合同原文及适用条款"),
        db,
        user,
    )
    assert result["review_status"] == "confirmed"
    db.refresh(contract)
    assert contract.requires_review is True
