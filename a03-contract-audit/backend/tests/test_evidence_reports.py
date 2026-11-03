"""统一证据报表快照与导出的隔离测试。"""
from io import BytesIO

import pytest
from docx import Document
from openpyxl import load_workbook
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.session import Base
from app.models.models import AuditBatch, AuditBatchItem, Contract, ContractClause, Rectification, Risk, User
from app.services.report.exporter import (
    build_report_snapshot,
    export_report_docx,
    export_report_xlsx,
)


def _database() -> tuple[Session, User]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    user = User(username="report-owner", password_hash="x", role="business", department="采购中心")
    db.add(user)
    db.flush()
    return db, user


def _contract(db: Session, user: User, filename: str, department: str = "采购中心") -> Contract:
    row = Contract(
        filename=filename,
        storage_path=f"/{filename}",
        department=department,
        uploaded_by=user.id,
        status="done",
        elements_json='{"party_a":"甲方","payment_terms":"验收后付款"}',
    )
    db.add(row)
    db.flush()
    return row


def _job(db: Session, user: User, contract: Contract, status: str, generation: int) -> AuditBatchItem:
    contract.audit_generation = generation
    batch = AuditBatch(
        owner_id=user.id,
        department=contract.department,
        idempotency_key=f"batch-{contract.id}-{generation}",
        status="completed",
    )
    db.add(batch)
    db.flush()
    item = AuditBatchItem(
        batch_id=batch.id,
        contract_id=contract.id,
        filename=contract.filename,
        status=status,
        audit_generation=generation,
        result_json='{"coverage":{"planned":4,"completed":4}}',
    )
    db.add(item)
    db.flush()
    return item


def test_snapshot_uses_only_latest_job_generation_and_has_stable_fingerprint():
    db, user = _database()
    contract = _contract(db, user, "采购合同.docx")
    old = _job(db, user, contract, "done", 1)
    latest = _job(db, user, contract, "failed", 2)
    db.add(Risk(
        contract_id=contract.id,
        audit_job_id=old.id,
        level="high",
        category="旧风险",
        original_text="旧原文",
        basis="旧依据",
        suggestion="旧建议",
    ))
    db.commit()

    first = build_report_snapshot(db, department_scope={"采购中心"})
    second = build_report_snapshot(db, department_scope={"采购中心"})

    assert first["report_id"] == second["report_id"]
    assert first["generated_at"] != ""
    assert first["contracts"][0]["job_id"] == latest.id
    assert first["summary"]["failed"] == 1
    assert first["risks"] == []
    assert any("失败" in note for note in first["notes"])


@pytest.mark.parametrize("contract_ids", [[], [0], [-1], [True], list(range(1, 202))])
def test_snapshot_rejects_invalid_explicit_contract_selection(contract_ids):
    db, _user = _database()
    with pytest.raises(ValueError):
        build_report_snapshot(db, contract_ids=contract_ids)


def test_snapshot_deduplicates_ids_and_distinguishes_missing_from_forbidden():
    db, user = _database()
    own = _contract(db, user, "本部门合同.docx")
    other = _contract(db, user, "其他部门合同.docx", "财务部")
    db.commit()

    selected = build_report_snapshot(db, [own.id, own.id], department_scope={"采购中心"})
    assert selected["contract_ids"] == [own.id]
    with pytest.raises(LookupError, match="不存在"):
        build_report_snapshot(db, [999], department_scope={"采购中心"})
    with pytest.raises(PermissionError):
        build_report_snapshot(db, [other.id], department_scope={"采购中心"})


def test_legacy_risk_and_verified_rectification_are_serialized():
    db, user = _database()
    contract = _contract(db, user, "无任务合同.docx")
    risk = Risk(
        contract_id=contract.id,
        level="medium",
        category="履约风险",
        original_text="原文",
        basis="依据",
        suggestion="建议",
        evidence_status="supported",
        original_text_verified=True,
    )
    db.add(risk)
    db.flush()
    db.add_all([
        Rectification(contract=contract.filename, risk=risk.category, level="medium", created="2026-09-17", due="2026-09-24", risk_id=risk.id),
        Rectification(contract="孤立", risk="孤立", level="low", created="2026-09-17", due="2026-09-24", risk_id=None),
    ])
    db.commit()

    snapshot = build_report_snapshot(db)

    assert snapshot["summary"]["unreviewed"] == 1
    assert snapshot["summary"]["supported"] == 0  # 历史词面验证不属于新版语义核验通过。
    assert [row["risk_id"] for row in snapshot["rectifications"]] == [risk.id]
    assert any("无审查任务" in note for note in snapshot["notes"])


def test_snapshot_serializes_applicability_rule_and_decision_trace():
    db, user = _database()
    contract = _contract(db, user, "带决策轨迹.docx")
    job = _job(db, user, contract, "done", 1)
    risk = Risk(
        contract_id=contract.id,
        audit_job_id=job.id,
        level="high",
        category="付款风险",
        original_text="验收前支付全部尾款",
        basis="付款条件待核验",
        suggestion="补充验收前置条件",
        applicability_status="unknown_as_of",
        applicability_reason_codes_json='["missing_effective_date"]',
        rule_executions_json='[{"rule_id":"PAY-001","rule_version":"v3","status":"hit","reason":"付款先于验收"}]',
        decision_trace_json='{"status":"manual_review","reason_codes":["RULE_RESULT_UNRESOLVED"]}',
    )
    db.add(risk)
    db.commit()

    row = build_report_snapshot(db)["risks"][0]

    assert row["applicability_status"] == "unknown_as_of"
    assert row["applicability_reason_codes"] == ["missing_effective_date"]
    assert row["rule_executions"][0]["rule_id"] == "PAY-001"
    assert row["decision_trace"] == {"status": "manual_review", "reason_codes": ["RULE_RESULT_UNRESOLVED"]}


def test_excel_and_word_are_readable_and_sanitize_formula_and_xml_controls():
    db, user = _database()
    contract = _contract(db, user, "=HYPERLINK(\"bad\")\x01合同.docx")
    _job(db, user, contract, "done", 1)
    db.add(Risk(
        contract_id=contract.id,
        audit_job_id=db.query(AuditBatchItem.id).scalar(),
        level="high",
        category="付款风险",
        original_text="很长的中文原文" * 80,
        basis="缺少明确付款条件",
        suggestion="补充验收与付款节点",
    ))
    db.commit()
    snapshot = build_report_snapshot(db)

    workbook = load_workbook(BytesIO(export_report_xlsx(snapshot)), data_only=False)
    assert {"摘要", "合同清单", "风险台账", "证据索引", "整改跟踪", "风险矩阵", "口径说明"} <= set(workbook.sheetnames)
    filename_cell = workbook["合同清单"]["B2"].value
    assert filename_cell.startswith("'")
    document = Document(BytesIO(export_report_docx(snapshot)))
    text = "\n".join(paragraph.text for paragraph in document.paragraphs)
    assert "合同审查证据报告" in text
    assert "\x01" not in text


def test_unlocated_evidence_is_not_counted_as_verified():
    db, user = _database()
    contract = _contract(db, user, "需定位.docx")
    db.add(Risk(contract_id=contract.id, level="low", category="付款", original_text="待核查", basis="依据", suggestion="建议", evidence_status="supported", original_text_verified=False))
    db.commit()
    assert build_report_snapshot(db)["summary"]["supported"] == 0


def test_export_rejects_changed_preview_and_supports_word():
    from fastapi import HTTPException
    from app.api.v1.endpoints.reports import export_report
    db, user = _database()
    contract = _contract(db, user, "所选.docx")
    db.commit()
    snapshot = build_report_snapshot(db, [contract.id])
    response = export_report(contract_ids=[contract.id], format="docx", report_id=snapshot["report_id"], db=db, user=user)
    assert response.media_type.endswith("wordprocessingml.document")
    contract.filename = "变更.docx"
    db.commit()
    with pytest.raises(HTTPException) as error:
        export_report(contract_ids=[contract.id], format="xlsx", report_id=snapshot["report_id"], db=db, user=user)
    assert error.value.status_code == 409


def test_empty_authorization_never_exports_all():
    db, user = _database()
    _contract(db, user, "私有.docx")
    db.commit()
    assert build_report_snapshot(db, department_scope=set())["summary"]["total"] == 0


def test_legacy_summary_has_no_compliance_inference_or_medium_top_risks():
    from app.services.report.exporter import report_summary
    db, user = _database()
    contract = _contract(db, user, "未审查.docx")
    db.add(Risk(contract_id=contract.id, level="medium", category="中风险", original_text="原文", basis="依据", suggestion="建议"))
    db.commit()
    result = report_summary(db)
    assert result["kpi"]["pass"] == 0
    assert result["tops"] == []
    assert result["trend"]["labels"][0].startswith("20")


def test_long_excel_evidence_is_split_without_loss():
    db, user = _database()
    contract = _contract(db, user, "长原文.docx")
    original = "原文内容" * 9000
    db.add(Risk(contract_id=contract.id, level="high", category="原文", original_text=original, basis="依据", suggestion="建议"))
    db.commit()
    workbook = load_workbook(BytesIO(export_report_xlsx(build_report_snapshot(db))))
    fragments = [row[5].value for row in workbook["风险台账"].iter_rows(min_row=2)]
    import re
    recovered = "".join(re.sub(r"^\[分段 \d+/\d+\] ", "", part) for part in fragments)
    assert recovered == original


def test_report_quality_uses_job_snapshot_not_current_contract():
    db, user = _database()
    contract = _contract(db, user, "质量快照.docx")
    contract.requires_review = True
    contract.review_reason = "后续解析信息"
    contract.ocr_confidence = 0.2
    job = _job(db, user, contract, "done", 1)
    job.result_json = '{"ocr_confidence":0.9,"coverage":{"planned":1,"completed":5}}'
    db.commit()
    row = build_report_snapshot(db)["contracts"][0]
    assert row["requires_review"] is False
    assert row["review_reason"] is None
    assert row["ocr_confidence"] == 0.9
    assert row["coverage"] is None


def test_date_confirmation_excludes_previous_job_results_but_keeps_historical_rectification():
    from app.api.v1.endpoints.contracts import confirm_sign_date
    from app.schemas.contract import SignDateConfirmation
    from app.services.report.exporter import export_risk_ledger
    db, user = _database()
    user.role = 'legal'
    contract = _contract(db, user, '日期变更报告.txt')
    contract.content_sha256 = 'same-file'
    old = _job(db, user, contract, 'done', 1)
    old.result_json = '{"coverage":{"planned":4,"completed":4},"cross_checks":[{"note":"旧任务冲突"}]}'
    risk = Risk(contract_id=contract.id, audit_job_id=old.id, category='旧付款风险', level='high',
                original_text='旧代次独有原文', basis='旧代次依据', suggestion='旧建议')
    db.add(risk)
    db.add(ContractClause(contract_id=contract.id, audit_generation=1, chunk_id='old-payment',
                          content='第一条 甲方应支付合同总价100%。'))
    db.flush()
    db.add(Rectification(contract=contract.filename, risk_id=risk.id, risk=risk.category, level='high',
                          status='已接受风险', created='2026-11-01', due='2026-11-07', residual_risk='历史履约风险仍在'))
    db.commit()
    confirmation = confirm_sign_date(contract.id, SignDateConfirmation(sign_date='2026-10-02'), db, user)
    assert confirmation['audit_invalidated'] is True

    snapshot = build_report_snapshot(db, [contract.id])
    current = snapshot['contracts'][0]
    assert current['audit_generation'] == contract.audit_generation == 2
    assert current['elements']['sign_date'] == '2026-10-02'
    assert current['job_id'] is None
    assert current['job_status'] is None
    assert current['coverage'] is None
    assert current['cross_checks'] == []
    assert current['requires_review'] is True
    assert '重新审查' in current['review_reason']
    assert current['payment_analysis']['status'] == 'unavailable'
    assert current['payment_analysis']['events'] == []
    assert snapshot['risks'] == []
    assert snapshot['summary']['completed'] == 0
    assert snapshot['summary']['unreviewed'] == 1
    assert snapshot['state'] == 'NO_COMPLETED_AUDIT'
    assert snapshot['operations']['high_risk_contracts'] == 0
    assert snapshot['operations']['accepted_risk_count'] == 1
    assert snapshot['rectifications'][0]['source_scope'] == 'historical'
    assert snapshot['rectifications'][0]['residual_risk'] == '历史履约风险仍在'
    assert any('重新审查' in note for note in snapshot['notes'])
    legacy_sheet = load_workbook(BytesIO(export_risk_ledger(db, [contract.id]))).active
    assert legacy_sheet.max_row == 1
    workbook = load_workbook(BytesIO(export_report_xlsx(snapshot)))
    risk_sheet_text = '\n'.join(str(cell.value) for row in workbook['风险台账'] for cell in row)
    payment_sheet_text = '\n'.join(str(cell.value) for row in workbook['付款节点'] for cell in row)
    assert '旧代次独有原文' not in risk_sheet_text
    assert '合同总价100%' not in payment_sheet_text
    word_text = '\n'.join(p.text for p in Document(BytesIO(export_report_docx(snapshot))).paragraphs)
    assert '重新审查' in word_text
    db.close()


def test_no_job_legacy_risk_remains_compatible_until_explicit_date_invalidation():
    from app.api.v1.endpoints.contracts import confirm_sign_date
    from app.schemas.contract import SignDateConfirmation
    db, user = _database()
    user.role = 'legal'
    contract = _contract(db, user, '无任务历史.txt')
    contract.audit_generation = 1
    contract.content_sha256 = 'same-file'
    risk = Risk(contract_id=contract.id, category='历史风险', level='medium', original_text='历史原文', basis='历史依据', suggestion='建议')
    db.add(risk)
    db.commit()
    assert [row['id'] for row in build_report_snapshot(db)['risks']] == [risk.id]
    db.rollback()
    confirm_sign_date(contract.id, SignDateConfirmation(sign_date='2026-10-02'), db, user)
    snapshot = build_report_snapshot(db)
    assert snapshot['risks'] == []
    assert snapshot['contracts'][0]['requires_review'] is True
    assert any('重新审查' in note for note in snapshot['notes'])
    db.close()


def test_current_generation_job_only_exports_its_risks_and_payment_clauses():
    db, user = _database()
    contract = _contract(db, user, '当前代次.txt')
    old = _job(db, user, contract, 'done', 1)
    current = _job(db, user, contract, 'done', 3)
    db.add_all([
        Risk(contract_id=contract.id, audit_job_id=old.id, category='旧风险', level='high', original_text='旧原文', basis='旧依据', suggestion='旧建议'),
        Risk(contract_id=contract.id, audit_job_id=current.id, category='新风险', level='low', original_text='新原文', basis='新依据', suggestion='新建议'),
        ContractClause(contract_id=contract.id, audit_generation=1, chunk_id='old-payment', content='甲方支付合同总价100%。'),
        ContractClause(contract_id=contract.id, audit_generation=3, chunk_id='new-payment', content='甲方验收后支付合同总价80%。'),
    ])
    db.commit()
    snapshot = build_report_snapshot(db)
    assert [row['category'] for row in snapshot['risks']] == ['新风险']
    assert snapshot['summary']['completed'] == 1
    assert snapshot['contracts'][0]['audit_generation'] == 3
    assert snapshot['contracts'][0]['job_id'] == current.id
    assert snapshot['contracts'][0]['payment_analysis']['total_percentage'] == '80'
    db.close()


def test_legacy_ledger_empty_selection_still_exports_all_authorized_current_risks():
    from app.services.report.exporter import export_risk_ledger
    db, user = _database()
    visible = _contract(db, user, '授权合同.txt')
    hidden = _contract(db, user, '其他部门合同.txt', department='其他部门')
    for contract in (visible, hidden):
        job = _job(db, user, contract, 'done', 1)
        db.add(Risk(contract_id=contract.id, audit_job_id=job.id, category='付款风险', level='high',
                    original_text='核对付款条款', basis='待核验', suggestion='人工复核'))
    db.commit()
    def rows(selection):
        workbook = load_workbook(BytesIO(export_risk_ledger(db, selection, department_scope={'采购中心'})))
        return list(workbook.active.values)
    assert rows([]) == rows(None)
    assert len(rows([])) == 2
    assert rows([])[1][0] == '授权合同.txt'
    db.close()
