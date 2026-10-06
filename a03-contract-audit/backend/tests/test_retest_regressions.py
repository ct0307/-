"""独立复测反例：覆盖正文、原文锚点及真实业务状态。"""
from io import BytesIO
from types import SimpleNamespace
from datetime import datetime, timezone

import pytest
from docx import Document

from app.api.v1.endpoints.contracts import _derive_status
from app.services.parser.elements import extract_element_result, merge_element_review
from app.services.parser.extractor import extract_uploaded_document, DocumentParseResult
from app.services.rag.contract_structure import build_contract_chunks, build_contract_windows


@pytest.mark.parametrize('ending', ['\n', '\r\n', ' ', '\n  '])
def test_unnumbered_contract_trailing_whitespace_keeps_all_text(ending):
    text = '甲方：甲公司\n合同金额：100元。' + ending
    chunks = build_contract_chunks(text)
    assert len(chunks) == 1
    assert chunks[0].text == text.strip()
    assert text[chunks[0].anchor.char_start:chunks[0].anchor.char_end] == chunks[0].text
    assert build_contract_windows(text)[0].text == text.strip()


def test_duration_alias_keeps_source_offsets():
    text = '履行期限：2026年10月1日至2026年12月31日。'
    result = extract_element_result(DocumentParseResult(text, 'native'))
    assert result.values['duration'] == '2026-10-1至2026-12-31'
    evidence = result.evidence['duration']
    assert text[evidence.start:evidence.end] == evidence.raw_text


def test_wrapped_payment_keeps_percentage_and_exact_evidence():
    text = '付款方式：签订后支付30%；发货前支付40%；验收后支付合同总\n价30%。\n争议解决：向法院起诉。'
    result = extract_element_result(DocumentParseResult(text, 'native'))
    assert result.values['payment_terms'][-1] == '验收后支付合同总价30%'
    evidence = result.evidence['payment_terms'][-1]
    assert text[evidence.start:evidence.end] == evidence.raw_text
    assert '争议解决' not in ''.join(result.values['payment_terms'])


def test_numbered_payment_wrap_keeps_amount():
    text = '付款方式：\n1. 签订后支付30%；\n2. 验收后支付合同总\n价70%。\n争议解决：向法院起诉。'
    result = extract_element_result(DocumentParseResult(text, 'native'))
    assert result.values['payment_terms'] == ['签订后支付30%', '验收后支付合同总价70%']
    for item in result.evidence['payment_terms']:
        assert text[item.start:item.end] == item.raw_text


def test_payment_continuation_starting_with_acceptance_is_not_a_heading():
    parsed = DocumentParseResult('付款方式：签订后支付30%；\n验收后支付70%。\n验收：按附件执行。', 'native')
    assert extract_element_result(parsed).values['payment_terms'] == ['签订后支付30%', '验收后支付70%']


def test_explicit_but_unextracted_field_requires_review_without_claiming_conflict():
    parsed = DocumentParseResult('甲方：\n乙方：乙公司\n履行期限：待商议。', 'native')
    review, reason = merge_element_review(parsed, extract_element_result(parsed))
    assert review
    assert '未能提取' in reason
    assert '冲突' not in reason


@pytest.mark.parametrize('payment_label', ['付款方式', '付款节点'])
def test_docx_table_key_value_fields_have_exact_evidence_without_false_conflict(payment_label):
    document = Document()
    table = document.add_table(rows=0, cols=2)
    pairs = [('甲方', '甲公司'), ('乙方', '乙公司'), ('合同标的', '设备采购'),
             ('合同金额', '100000元'), ('履行期限', '2026年10月1日至2026年12月31日'),
             (payment_label, '签订后支付30%；验收后支付70%')]
    for key, value in pairs:
        cells = table.add_row().cells
        cells[0].text, cells[1].text = key, value
    stream = BytesIO()
    document.save(stream)
    parsed = extract_uploaded_document('表格.docx', stream.getvalue())
    result = extract_element_result(parsed)
    assert result.values == dict(party_a='甲公司', party_b='乙公司', subject='设备采购',
                                amount='100000元', duration='2026-10-1至2026-12-31',
                                payment_terms=['签订后支付30%', '验收后支付70%'])
    assert not result.review_fields
    for evidence in result.evidence.values():
        for item in evidence if isinstance(evidence, list) else [evidence]:
            assert parsed.text[item.start:item.end] == item.raw_text
            assert item.validation == 'valid'


def test_payment_spanning_two_lines_on_same_page_is_located():
    from app.services.parser.extractor import DocumentBlock, SourceAnchor
    text = '付款方式：验收后支付合同总\n价30%。'
    parsed = DocumentParseResult(text,'native',blocks=tuple(
        DocumentBlock(str(i),'page_text',line,SourceAnchor(page_number=1))
        for i,line in enumerate(text.splitlines())))
    result = extract_element_result(parsed)
    assert result.evidence['payment_terms'][0].page == 1
    assert not result.review_fields


@pytest.mark.parametrize('status,expected', [('uploaded', '未审查'), ('parsed', '未审查'),
    ('auditing', '审查中'), ('audit_failed', '审查失败')])
def test_history_never_labels_unfinished_contract_compliant(status, expected):
    assert _derive_status(SimpleNamespace(status=status, requires_review=False), []) == expected


def test_history_timestamp_preserves_utc_in_sqlite():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.db.session import Base
    from app.models.models import Contract, User
    from app.api.v1.endpoints.contracts import list_contracts_history
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = User(username='time-test', password_hash='test', role='admin')
        db.add(user)
        db.flush()
        db.add(Contract(filename='test.txt',storage_path='unused',uploaded_by=user.id,
                        created_at=datetime(2026,10,6,9,0),status='parsed'))
        db.commit()
        row = list_contracts_history(db,user)[0]
        assert datetime.fromisoformat(row.time) == datetime(2026,10,6,9,0,tzinfo=timezone.utc)
        assert row.status == '未审查'
    engine.dispose()


def test_normal_model_conclusion_is_not_persisted_as_risk(monkeypatch):
    from app.services.audit import auditor
    from app.services.audit.protocol import AgentReviewResult, ReviewedRiskCandidate
    monkeypatch.setattr(auditor, 'retrieve', lambda *a, **k: [])
    monkeypatch.setattr(auditor, '_review_window_requests', lambda *a, **k: [AgentReviewResult(
        complete=True, candidates=[ReviewedRiskCandidate(level='low', category='争议解决条款',
            quote='向甲方所在地有管辖权的人民法院起诉。', reason='争议解决条款约定向甲方所在地有管辖权的人民法院起诉，管辖约定明确，符合法律规定，未发现明显风险。',
            suggestion='无需修改，该条款已明确管辖法院，可继续保留。',
            source_window_id='test-window', source_clause_ids=[])]
    )])
    result = auditor._agent_audit('legal', {}, '向甲方所在地有管辖权的人民法院起诉。', {})
    assert result.risks == []
    assert result.planned == result.completed == 1


@pytest.mark.parametrize('reason,suggestion', [
    ('该条款已明确管辖法院，但可能违反专属管辖要求。', '无需修改其他内容，应当核实管辖。'),
    ('未发现风险，依据不足需人工确认。', '无需修改，待确认。'),
    ('该条款已明确合同金额，但付款比例过高。', '可保留主体信息，建议降低预付款。'),
    ('未发现风险。', '无需修改甲方名称，但应补充验收标准。'),
])
def test_uncertain_or_mixed_normal_conclusions_are_kept(reason, suggestion):
    from app.services.audit.auditor import _is_explicit_normal_conclusion
    assert not _is_explicit_normal_conclusion(reason, suggestion)
