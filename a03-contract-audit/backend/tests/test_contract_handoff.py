import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.db.session import Base
from app.models.models import Contract, User


def test_submit_accept_and_return_preserve_processing_state():
    from app.api.v1.endpoints.handoffs import transition_handoff, HandoffAction, list_handoffs
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        business = User(username="business", password_hash="x", role="business", department="采购")
        legal = User(username="legal", password_hash="x", role="legal", department="法务", authorized_departments_json='["采购"]')
        stranger = User(username="stranger", password_hash="x", role="legal", department="销售")
        db.add_all([business, legal, stranger]); db.flush()
        contract = Contract(filename="测试.txt", storage_path="unused", uploaded_by=business.id, department="采购", status="parsed", contract_type="采购合同")
        db.add(contract); db.commit()
        submit = HandoffAction(action="submit", expected_version=0)
        first = transition_handoff(contract.id, submit, db, business)
        assert first["state"] == "submitted"
        assert transition_handoff(contract.id, submit, db, business)["version"] == 1
        assert len(list_handoffs(db, legal)["items"]) == 1
        with pytest.raises(HTTPException) as denied:
            transition_handoff(contract.id, HandoffAction(action="accept", expected_version=1), db, stranger)
        assert denied.value.status_code == 403
        accepted = transition_handoff(contract.id, HandoffAction(action="accept", expected_version=1), db, legal)
        assert accepted["assigned_to"] == legal.id
        assert contract.status == "parsed"
        returned = transition_handoff(contract.id, HandoffAction(action="return", expected_version=2, reason="请补充合同附件"), db, legal)
        assert returned["state"] == "returned"
        assert transition_handoff(contract.id, HandoffAction(action="submit", expected_version=3), db, business)["state"] == "submitted"
        with pytest.raises(HTTPException) as stale:
            transition_handoff(contract.id, HandoffAction(action="return", expected_version=1, reason="过期操作"), db, legal)
        assert stale.value.status_code == 409
