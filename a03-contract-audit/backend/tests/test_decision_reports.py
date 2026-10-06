"""审批报告保留原始证据、缺项与真实责任，不替授权人员作决定。"""
from io import BytesIO
from copy import deepcopy
import re
from docx import Document
from openpyxl import load_workbook
from app.services.report.decision_brief import decision_brief, evidence_verified
from app.services.report.renderers import export_report_xlsx, export_report_docx
from tests.test_evidence_reports import _database, _contract, _job
from app.models.models import Risk, Rectification
from app.services.report.exporter import build_report_snapshot


def sample():
    db, user = _database()
    contract = _contract(db, user, '=HYPERLINK("bad")合同.docx')
    job = _job(db, user, contract, 'review_required', 1)
    contract.elements_json = '{"party_a":"甲公司","party_b":"乙公司","subject":"设备采购","amount":"人民币10万元","duration":"一年","payment_terms":"验收付款"}'
    risk = Risk(contract_id=contract.id, audit_job_id=job.id, level='high',
                category='付款条件', original_text='超长原文' * 9000,
                risk_reason='付款前缺验收条件', basis='无可靠检索依据，请人工复核',
                suggestion='明确验收前置条件', review_status='pending',
                evidence_status='supported', original_text_verified=True)
    db.add(risk)
    db.flush()
    db.add(Rectification(contract=contract.filename, risk=risk.category, risk_id=risk.id,
                         level='high', owner='张某', due='2026-10-10', created='2026-10-02', status='处理中'))
    db.commit()
    return build_report_snapshot(db)


def test_brief_does_not_treat_legacy_support_or_confirmation_as_approval():
    snapshot = sample()
    brief = decision_brief(snapshot)
    assert brief['status'] == '待补充与专业复核'
    assert brief['unverified'] == 1
    assert brief['issues'][0]['owner'] == '张某'
    assert brief['issues'][0]['due'] == '2026-10-10'
    assert not evidence_verified(snapshot['risks'][0])
    snapshot['risks'][0]['review_status'] = 'confirmed'
    assert decision_brief(snapshot)['human_confirmed'] == 1
    assert decision_brief(snapshot)['status'] != '同意签署'


def test_excel_full_detail_preserves_long_text_and_safe_cells():
    snapshot = sample()
    wb = load_workbook(BytesIO(export_report_xlsx(snapshot)))
    ws = wb['风险详情']
    original = ''.join(row[2].value for row in ws.iter_rows(min_row=2) if re.fullmatch(r'原文(?:（续\d+）)?', str(row[1].value)))
    assert original == snapshot['risks'][0]['original_text']
    assert all(c.data_type != 'f' for sheet in wb for row in sheet for c in row)
    assert wb['合同清单']['P2'].value == '乙公司'
    assert wb['合同清单']['Q2'].value == '一年'
    assert wb['审批重点']['L2'].hyperlink.target.startswith("#'风险详情'!A")
    assert wb['审批重点']['I2'].value == '张某'


def test_word_keeps_original_and_unsigned_approval_fields():
    snapshot = sample()
    doc = Document(BytesIO(export_report_docx(snapshot)))
    text = '\n'.join(p.text for p in doc.paragraphs)
    assert snapshot['risks'][0]['original_text'] in text
    assert '付款前缺验收条件' in text
    assert '不会自动回写系统' in text
    assert '待补充与专业复核' in text
    assert '无可靠检索依据' in text
    approval = next(t for t in doc.tables if t.cell(0,0).text == '角色')
    assert all(row.cells[1].text == '' and row.cells[2].text == '' for row in approval.rows[1:])


def test_missing_actions_and_ignored_risks_are_not_fabricated_or_promoted():
    snapshot = sample()
    snapshot['rectifications'] = []
    snapshot['risks'][0]['review_status'] = 'ignored'
    brief = decision_brief(snapshot)
    assert brief['focus'] == []
    assert brief['issues'][0]['owner'] == '待分派'
    assert brief['issues'][0]['due'] == '待约定'
    assert brief['issues'][0]['action_status'] == '尚未建立整改任务'


def test_multiple_contracts_are_listed_without_summing_unverified_amount():
    snapshot = sample()
    another = deepcopy(snapshot['contracts'][0])
    another['id'] += 100
    another['filename'] = '外币合同.docx'
    another['amount'] = 'USD 200'
    snapshot['contracts'].append(another)
    snapshot['summary']['total'] = 2
    wb = load_workbook(BytesIO(export_report_xlsx(snapshot)))
    assert '不汇总为风险敞口' in wb['摘要']['A11'].value
    assert wb['合同清单']['H3'].value == 'USD 200'
