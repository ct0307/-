"""历史台账只能根据当前任务的完整审查证据给出整体结论。"""
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.v1.endpoints.contracts import get_contract_risks, list_contracts_history
from app.db.session import Base
from app.models.models import AuditBatch, AuditBatchItem, Contract, Risk, User


@pytest.fixture
def history_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = User(username="history-owner", password_hash="x", role="admin")
        db.add(user)
        db.flush()
        contract = Contract(
            filename="合成合同.txt", storage_path="unused", uploaded_by=user.id,
            status="done", audit_generation=1,
        )
        db.add(contract)
        db.flush()
        yield db, user, contract
    engine.dispose()


def _job(db, user, contract, *, status="done", generation=1, payload=None):
    batch = AuditBatch(
        owner_id=user.id, department="", idempotency_key=f"job-{generation}",
    )
    db.add(batch)
    db.flush()
    job = AuditBatchItem(
        batch_id=batch.id, contract_id=contract.id, filename=contract.filename,
        status=status, audit_generation=generation,
        result_json=json.dumps(payload if payload is not None else {
            "coverage": {"planned": 2, "completed": 2},
            "quality_reasons": [], "issues": [],
        }),
    )
    db.add(job)
    db.flush()
    return job


def _row(history_db):
    db, user, _contract = history_db
    db.commit()
    return list_contracts_history(db=db, user=user)[0]


def _risk(contract, job, level):
    return Risk(
        contract_id=contract.id, audit_job_id=job.id, level=level,
        category="合成风险", original_text="合成条款", basis="合成依据", suggestion="请核对条款",
    )


@pytest.mark.parametrize("status", [
    "uploaded", "parsed", "queued", "parsing", "auditing", "reviewing",
    "validating", "audit_failed", "failed", "review_required", "done",
])
def test_history_without_complete_quality_evidence_never_reports_low_risk(history_db, status):
    _db, _user, contract = history_db
    contract.status = status
    row = _row(history_db)
    assert row.level == "尚无法判断"
    assert row.riskCount == 0
    assert row.assessmentComplete is False
    assert row.status not in {"合规", "未发现风险", "已整改"}


@pytest.mark.parametrize("coverage", [
    None, {}, {"planned": 0, "completed": 0}, {"planned": 2, "completed": 1},
    {"planned": 1, "completed": 2}, {"planned": True, "completed": 1},
])
def test_history_done_with_missing_or_incomplete_coverage_is_undetermined(history_db, coverage):
    db, user, contract = history_db
    _job(db, user, contract, payload={"coverage": coverage})
    row = _row(history_db)
    assert row.level == "尚无法判断"
    assert row.assessmentComplete is False
    assert row.status == "待人工复核"


@pytest.mark.parametrize("quality", [
    {"requires_review": True}, {"quality_reasons": ["OUTPUT_TRUNCATED"]},
    {"issues": [{"code": "INVALID_MODEL_OUTPUT"}]},
    {"issues": None}, {"issues": ""}, {"quality_reasons": 0},
    {"status": "audit_failed"},
])
def test_history_quality_issues_prevent_complete_conclusion(history_db, quality):
    db, user, contract = history_db
    _job(db, user, contract, payload={"coverage": {"planned": 2, "completed": 2}, **quality})
    row = _row(history_db)
    assert row.level == "尚无法判断"
    assert row.assessmentComplete is False


def test_history_complete_empty_audit_says_no_risks_found(history_db):
    db, user, contract = history_db
    _job(db, user, contract)
    row = _row(history_db)
    assert row.level == "未发现风险"
    assert row.status == "未发现风险"
    assert row.assessmentComplete is True
    assert row.coverage.model_dump() == {"planned": 2, "completed": 2}


@pytest.mark.parametrize("job_status,expected", [("failed", "审查失败"), ("reviewing", "审查中")])
def test_latest_job_overrides_stale_done_contract_and_old_risks(history_db, job_status, expected):
    db, user, contract = history_db
    old = _job(db, user, contract)
    db.add(_risk(contract, old, "high"))
    contract.audit_generation = 2
    _job(db, user, contract, status=job_status, generation=2)
    row = _row(history_db)
    assert row.level == "尚无法判断"
    assert row.status == expected
    assert row.riskCount == 0
    assert row.assessmentComplete is False


def test_history_old_generation_complete_snapshot_cannot_prove_current_audit(history_db):
    db, user, contract = history_db
    _job(db, user, contract)
    contract.audit_generation = 2
    assert _row(history_db).level == "尚无法判断"


def test_history_partial_candidate_count_is_preserved_without_complete_rating(history_db):
    db, user, contract = history_db
    contract.status = "review_required"
    job = _job(db, user, contract, status="review_required", payload={
        "coverage": {"planned": 2, "completed": 1},
    })
    db.add(_risk(contract, job, "high"))
    row = _row(history_db)
    assert row.riskCount == 1
    assert row.level == "尚无法判断"
    assert row.assessmentComplete is False


def test_history_complete_audit_with_risks_still_aggregates_highest_level(history_db):
    db, user, contract = history_db
    job = _job(db, user, contract)
    db.add_all([
        _risk(contract, job, "low"),
        _risk(contract, job, "high"),
    ])
    row = _row(history_db)
    assert row.level == "高风险"
    assert row.riskCount == 2
    assert row.assessmentComplete is True


@pytest.mark.parametrize("complete", [True, False])
def test_legacy_generation_zero_risk_count_matches_task_details(history_db, complete):
    db, user, contract = history_db
    contract.audit_generation = 0
    job = _job(db, user, contract, generation=0, payload=None if complete else {})
    risk = _risk(contract, job, "high")
    risk.audit_job_id = None
    db.add(risk)

    row = _row(history_db)
    details = get_contract_risks(contract.id, job_id=job.id, db=db, user=user)

    assert len(details) == 1
    assert row.riskCount == len(details)
    assert row.level == ("高风险" if complete else "尚无法判断")
    assert row.status != "未发现风险"
    assert row.assessmentComplete is complete
