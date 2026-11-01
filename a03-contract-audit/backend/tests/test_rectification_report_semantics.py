"""风险接受与整改消除在报告中保持独立，不把责任决策误记为消除。"""
from datetime import date
from io import BytesIO

from docx import Document
from openpyxl import load_workbook

from app.services.report.operations import operational_summary
from app.services.report.decision_brief import decision_brief
from tests.test_decision_reports import sample
from app.services.report.renderers import export_report_xlsx, export_report_docx
from tests.test_evidence_reports import _database, _contract
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
