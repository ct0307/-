import json

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

from app.db.session import Base
from app.models import models
from app.services.parser.extractor import DocumentBlock, DocumentParseResult, SourceAnchor


def test_models_define_contract_clauses_and_risk_trace_fields():
    assert hasattr(models, "ContractClause")

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    inspector = inspect(engine)

    assert "contract_clauses" in inspector.get_table_names()
    clause_columns = {
        column["name"] for column in inspector.get_columns("contract_clauses")
    }
    assert {
        "contract_id",
        "audit_generation",
        "chunk_id",
        "clause_id",
        "clause_path_json",
        "content",
        "char_start",
        "char_end",
        "source_anchors_json",
    } <= clause_columns

    risk_columns = {column["name"] for column in inspector.get_columns("risks")}
    assert {
        "claim_id",
        "claim_status",
        "source_window_id",
        "source_clause_ids_json",
        "evidence_ids_json",
        "retrieval_attempts_json",
        "contract_evidence_json",
    } <= risk_columns

    engine.dispose()


def test_contract_clause_identity_is_unique_per_audit_generation():
    assert hasattr(models, "ContractClause")
    clause_model = models.ContractClause
    unique_columns = {
        tuple(column.name for column in constraint.columns)
        for constraint in clause_model.__table__.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }

    assert ("contract_id", "audit_generation", "chunk_id") in unique_columns


def test_risk_trace_json_defaults_are_valid_lists():
    assert hasattr(models, "ContractClause")
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        risk = models.Risk(
            contract_id=1,
            level="medium",
            category="付款风险",
            original_text="验收后付款",
            basis="待核验",
            suggestion="补充付款期限",
        )
        db.add(risk)
        db.flush()

        assert json.loads(risk.source_clause_ids_json) == []
        assert json.loads(risk.evidence_ids_json) == []
        assert json.loads(risk.retrieval_attempts_json) == []
        assert json.loads(risk.contract_evidence_json) == []

    engine.dispose()


def test_replace_contract_clauses_persists_source_anchors():
    from app.services.audit.evidence_persistence import replace_contract_clauses

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    parsed = DocumentParseResult(
        text="第一条 项目内容。\n第二条 验收后十日内付款。",
        source="native",
        blocks=(
            DocumentBlock(
                block_id="pdf-page-1-line-1",
                block_type="page_text",
                text="第一条 项目内容。",
                anchor=SourceAnchor(page_number=1, bbox=(10.0, 20.0, 100.0, 32.0)),
            ),
            DocumentBlock(
                block_id="pdf-page-2-line-1",
                block_type="page_text",
                text="第二条 验收后十日内付款。",
                anchor=SourceAnchor(page_number=2, bbox=(12.0, 24.0, 180.0, 38.0)),
            ),
        ),
    )

    with Session(engine) as db:
        clauses = replace_contract_clauses(
            db,
            contract_id=7,
            audit_generation=3,
            parsed=parsed,
        )
        db.flush()

        assert [clause.clause_id for clause in clauses] == ["第一条", "第二条"]
        assert clauses[1].audit_generation == 3
        assert json.loads(clauses[1].clause_path_json) == ["第二条"]
        anchors = json.loads(clauses[1].source_anchors_json)
        assert anchors == [{
            "page_number": 2,
            "bbox": [12.0, 24.0, 180.0, 38.0],
            "paragraph_index": None,
            "table_index": None,
            "row_index": None,
            "char_start": None,
            "char_end": None,
        }]

    engine.dispose()


def test_build_contract_evidence_prefers_exact_quote_match():
    from app.services.audit.evidence_persistence import build_contract_evidence

    clause = models.ContractClause(
        contract_id=1,
        audit_generation=1,
        chunk_id="clause-payment",
        clause_id="第二条",
        clause_path_json='["第二章 付款", "第二条"]',
        content="第二条 甲方应在验收后 十日内付款。",
        char_start=20,
        char_end=42,
        source_anchors_json='[{"page_number": 2, "bbox": [1, 2, 3, 4]}]',
    )

    evidence = build_contract_evidence(
        {"original_text": "验收后十日内付款", "source_clause_ids": ["第一条"]},
        [clause],
    )

    assert evidence == [{
        "chunk_id": "clause-payment",
        "clause_id": "第二条",
        "clause_path": ["第二章 付款", "第二条"],
        "char_start": 20,
        "char_end": 42,
        "anchors": [{"page_number": 2, "bbox": [1, 2, 3, 4]}],
        "match_type": "exact_quote",
        "score": 1.0,
    }]


def test_build_contract_evidence_marks_window_hint_as_non_exact():
    from app.services.audit.evidence_persistence import build_contract_evidence

    clause = models.ContractClause(
        contract_id=1,
        audit_generation=1,
        chunk_id="clause-hint",
        clause_id="第三条",
        clause_path_json='["第三条"]',
        content="第三条 付款安排由双方另行协商。",
        source_anchors_json="[]",
    )

    evidence = build_contract_evidence(
        {"original_text": "模型生成的概括文本", "source_clause_ids": ["第三条"]},
        [clause],
    )

    assert len(evidence) == 1
    assert evidence[0]["match_type"] == "clause_hint"
    assert evidence[0]["score"] < 1


def test_build_contract_evidence_does_not_invent_location_without_match():
    from app.services.audit.evidence_persistence import build_contract_evidence

    clause = models.ContractClause(
        contract_id=1,
        audit_generation=1,
        chunk_id="clause-unrelated",
        clause_id="第一条",
        clause_path_json='["第一条"]',
        content="第一条 项目内容为系统开发。",
        source_anchors_json="[]",
    )

    assert build_contract_evidence(
        {"original_text": "不存在的原文", "source_clause_ids": []},
        [clause],
    ) == []
