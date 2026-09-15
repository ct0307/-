"""六要素证据持久化与旧 API 兼容契约。"""

import json

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.v1.endpoints import contracts
from app.db import init_db
from app.db.session import Base
from app.models.models import Contract, User
from app.services.parser.elements import element_evidence_payload
from app.services.parser.extractor import (
    DocumentBlock,
    DocumentParseResult,
    SourceAnchor,
)


def _parsed(text: str) -> DocumentParseResult:
    return DocumentParseResult(
        text=text,
        source="native",
        blocks=(DocumentBlock(
            "p1",
            "page_text",
            text,
            SourceAnchor(page_number=1),
        ),),
    )


def test_parse_response_keeps_flat_values_and_adds_evidence(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    parsed = _parsed("甲方：之江科技有限公司\n合同总价为100万元。")
    monkeypatch.setattr(contracts, "extract_document", lambda _path: parsed)

    with Session(engine) as db:
        user = User(
            username="evidence-user",
            password_hash="x",
            role="legal",
            department="法务部",
        )
        db.add(user)
        db.flush()
        contract = Contract(
            filename="evidence.txt",
            storage_path="evidence.txt",
            uploaded_by=user.id,
            department=user.department,
        )
        db.add(contract)
        db.commit()

        response = contracts.parse_contract(contract.id, db=db, user=user)
        db.refresh(contract)

        assert response.elements["party_a"] == "之江科技有限公司"
        assert isinstance(response.elements["payment_terms"], (str, type(None)))
        evidence = response.element_evidence["party_a"]
        assert evidence["raw_text"] == "之江科技有限公司"
        assert evidence["page"] == 1
        assert evidence["start"] >= 0
        stored = json.loads(contract.element_evidence_json)
        assert stored["schema_version"] == 1
        assert stored["fields"]["amount"]["validation"] == "valid"

    engine.dispose()


def test_evidence_payload_keeps_review_fields_and_field_shapes():
    from app.services.parser.elements import extract_element_result

    result = extract_element_result(_parsed("甲方：甲公司\n采购方：乙公司"))
    payload = element_evidence_payload(result)

    assert payload["schema_version"] == 1
    assert payload["review_fields"] == ["party_a"]
    assert payload["fields"]["party_a"]["validation"] == "ambiguous"


def test_sqlite_dev_migration_declares_element_evidence_column():
    contract_columns = dict(init_db._DEV_COLUMNS["contracts"])

    assert contract_columns["element_evidence_json"] == "TEXT DEFAULT '{}' NOT NULL"
