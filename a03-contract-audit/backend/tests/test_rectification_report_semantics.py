"""风险接受与整改消除在报告中保持独立，不把责任决策误记为消除。"""
from datetime import date
from io import BytesIO
import pytest

from docx import Document
from openpyxl import load_workbook

from app.services.report.operations import operational_summary
from app.services.report.decision_brief import decision_brief
from tests.test_decision_reports import sample
from app.services.report.renderers import export_report_xlsx, export_report_docx
from tests.test_evidence_reports import _database, _contract, _job
from app.models.models import Rectification, RectificationEvent, Risk
from app.services.report.exporter import build_report_snapshot
from datetime import datetime, timezone
import json


def test_accepted_risk_is_separate_from_closed_and_action_overdue():
    snapshot = {
        "contracts": [{"id": 1, "department": "采购", "risk_high": 1, "risk_total": 1}],
        "risks": [{"review_status": "confirmed"}],
        "rectifications": [
            {"id": 1, "risk_id": 1, "status": "已接受风险", "due": "2026-01-01", "residual_risk": "预付款仍有履约风险"},
            {"id": 2, "risk_id": 1, "status": "已闭环", "due": "2026-01-01"},
            {"id": 3, "risk_id": 1, "status": "待风险接受", "due": "2026-01-01"},
        ],
    }
    result = operational_summary(snapshot, today=date(2026, 11, 1))
    assert result["closed_rectification_count"] == 1
    assert result["accepted_risk_count"] == 1
    assert result["risk_acceptance_pending_count"] == 1
    assert result["overdue_count"] == 1
    assert result["high_risk_contracts"] == 1
    assert result["accepted_risk_actions"][0]["residual_risk"] == "预付款仍有履约风险"


def test_decision_brief_explicitly_keeps_accepted_residual_risk():
    snapshot = sample()
    snapshot["rectifications"][0].update(
        status="已接受风险", acceptance_reason="经授权接受", residual_risk="供应商交付仍可能延迟",
    )
    brief = decision_brief(snapshot)
    assert "1项风险已经接受但仍保留剩余风险" in brief["note"]
    assert "剩余风险" in brief["issues"][0]["action_status"]


def test_export_keeps_acceptance_criteria_material_fingerprint_and_review_history():
    snapshot = sample()
    snapshot["rectifications"][0].update(
        acceptance_criteria="验收单签章齐备后付款", contract_stage="signed", handling_method="supplement",
        resolution="补充协议已签署", review_comment="已独立核对签章", submitted_by=1, reviewed_by=2,
        evidence=[{"contract_id": 9, "filename": "补充协议.docx", "content_sha256": "a" * 64}],
        events=[{"actor": "复核员", "action": "approve", "occurred_at": "2026-11-01T00:00:00Z",
                 "from_status": "待复核", "to_status": "已闭环", "snapshot": {"review_comment": "前轮因缺签章退回"}}],
    )
    wb = load_workbook(BytesIO(export_report_xlsx(snapshot)))
    assert "整改验收记录" in wb.sheetnames
    sheet_text = "\n".join(str(cell.value) for row in wb["整改验收记录"] for cell in row)
    for phrase in ("验收单签章齐备后付款", "补充协议.docx", "a" * 64, "前轮因缺签章退回"):
        assert phrase in sheet_text
    doc = Document(BytesIO(export_report_docx(snapshot)))
    text = "\n".join(paragraph.text for paragraph in doc.paragraphs)
    assert "验收单签章齐备后付款" in text
    assert "补充协议.docx" in text
    assert "前轮因缺签章退回" in text


def test_snapshot_keeps_persisted_evidence_and_event_history_after_reload():
    db, user = _database()
    contract = _contract(db, user, "整改来源.txt")
    risk = Risk(contract_id=contract.id, category="付款风险", level="high", original_text="预付款", basis="待核验", suggestion="补充保函")
    db.add(risk)
    db.flush()
    task = Rectification(contract=contract.filename, risk=risk.category, level=risk.level, risk_id=risk.id,
                         owner=user.username, created="2026-11-01", due="2026-11-07",
                         acceptance_criteria="保函可核验", contract_stage="signed", handling_method="performance",
                         resolution="已核对保函原件", submitted_by=user.id,
                         evidence_json=json.dumps([{"contract_id": 99, "filename": "保函凭证.txt", "content_sha256": "b" * 64}]))
    db.add(task)
    db.flush()
    db.add(RectificationEvent(rectification_id=task.id, actor_id=user.id, actor=user.username,
                              action="submit", occurred_at=datetime.now(timezone.utc), from_status="处理中", to_status="待复核",
                              snapshot_json='{"resolution":"第一次提交已退回"}'))
    db.commit()
    db.expire_all()
    row = build_report_snapshot(db)["rectifications"][0]
    assert row["acceptance_criteria"] == "保函可核验"
    assert row["resolution"] == "已核对保函原件"
    assert row["evidence"][0]["content_sha256"] == "b" * 64
    assert row["events"][0]["snapshot"]["resolution"] == "第一次提交已退回"
    db.close()


@pytest.mark.parametrize("latest_status", ["done", "review_required", "failed", "queued"])
def test_reaudit_keeps_historical_rectification_without_counting_old_risk(latest_status):
    db, user = _database()
    contract = _contract(db, user, "重审来源.txt")
    old_job = _job(db, user, contract, "done", 1)
    risk = Risk(contract_id=contract.id, audit_job_id=old_job.id, category="旧付款风险", level="high",
                original_text="预付款", basis="待核验", suggestion="补充保函", review_status="confirmed")
    db.add(risk)
    db.flush()
    task = Rectification(contract=contract.filename, risk=risk.category, level=risk.level, risk_id=risk.id,
                         owner=user.username, status="已接受风险", created="2026-11-01", due="2026-11-07",
                         residual_risk="履约争议仍存在")
    db.add(task)
    db.flush()
    db.add(RectificationEvent(rectification_id=task.id, actor_id=user.id, actor=user.username,
                             action="accept", occurred_at=datetime.now(timezone.utc), from_status="待风险接受",
                             to_status="已接受风险", snapshot_json='{"residual_risk":"履约争议仍存在"}'))
    latest_job = _job(db, user, contract, latest_status, 2)
    contract.audit_generation = 2
    db.commit()

    snapshot = build_report_snapshot(db, [contract.id], department_scope={contract.department})

    assert snapshot["risks"] == []
    assert snapshot["summary"]["risks"] == 0
    assert snapshot["operations"]["high_risk_contracts"] == 0
    assert snapshot["operations"]["accepted_risk_count"] == 1
    saved = snapshot["rectifications"][0]
    assert saved["contract_id"] == contract.id
    assert saved["audit_job_id"] == old_job.id != latest_job.id
    assert saved["audit_generation"] == 1
    assert saved["source_scope"] == "historical"
    assert saved["residual_risk"] == "履约争议仍存在"
    assert saved["events"][0]["snapshot"]["residual_risk"] == "履约争议仍存在"
    assert build_report_snapshot(db, department_scope=set())["rectifications"] == []

    workbook = load_workbook(BytesIO(export_report_xlsx(snapshot)))
    excel_text = "\n".join(str(cell.value) for row in workbook["整改验收记录"] for cell in row)
    assert "历史审查整改（不计入当前风险发现）" in excel_text
    assert "代次 1" in excel_text
    document = Document(BytesIO(export_report_docx(snapshot)))
    word_text = "\n".join(paragraph.text for paragraph in document.paragraphs)
    assert "历史审查整改（不计入当前风险发现）" in word_text
    assert "代次 1" in word_text
    assert "履约争议仍存在" in word_text
    db.close()


def test_historical_and_current_tasks_keep_selected_contract_and_department_scope():
    db, user = _database()
    contract = _contract(db, user, "所选合同.txt")
    excluded = _contract(db, user, "未选择合同.txt")
    foreign = _contract(db, user, "其他部门合同.txt", department="财务部")
    old_job = _job(db, user, contract, "done", 1)
    current_job = _job(db, user, contract, "done", 2)
    records = []
    for source, job, status in [(contract, old_job, "已接受风险"),
                                (contract, current_job, "处理中"),
                                (excluded, None, "已接受风险"), (foreign, None, "已接受风险")]:
        risk = Risk(contract_id=source.id, audit_job_id=job.id if job else None, category=source.filename,
                    level="medium", original_text="条款", basis="待核验", suggestion="修改", review_status="confirmed")
        db.add(risk)
        db.flush()
        task = Rectification(contract=source.filename, risk=risk.category, level=risk.level, risk_id=risk.id,
                             owner=user.username, status=status, created="2026-11-01", due="2026-11-07")
        db.add(task)
        records.append((risk, task))
    contract.audit_generation = 2
    db.commit()

    snapshot = build_report_snapshot(db, [contract.id], department_scope={contract.department})

    assert [risk["id"] for risk in snapshot["risks"]] == [records[1][0].id]
    assert snapshot["summary"]["risks"] == 1
    assert snapshot["operations"]["accepted_risk_count"] == 1
    assert [task["risk_id"] for task in snapshot["rectifications"]] == [records[0][0].id, records[1][0].id]
    assert [task["source_scope"] for task in snapshot["rectifications"]] == ["historical", "current"]
    assert [task["audit_generation"] for task in snapshot["rectifications"]] == [1, 2]
    assert all(task["contract_id"] == contract.id for task in snapshot["rectifications"])
    unselected_snapshot = build_report_snapshot(db, department_scope={contract.department})
    assert records[2][1].id in {task["id"] for task in unselected_snapshot["rectifications"]}
    assert records[3][1].id not in {task["id"] for task in unselected_snapshot["rectifications"]}
    db.close()
