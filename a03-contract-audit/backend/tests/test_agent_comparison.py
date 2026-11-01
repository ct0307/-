"""专业分工实验的输入泄漏、预算、失败与盲评保护。"""
import json
from types import SimpleNamespace

import pytest

from evaluation.agent_comparison import clean_text, arm_calls, parse_output, execute_arm, blind_rows, extract_text
from evaluation.agent_comparison_score import score_review


def test_cleaning_preserves_underlying_clause():
    source = '合成测试样本，仅用于系统验收\n案例编号：F3-001\n特别责任安排\n损失由供应方全部承担。双方确认该条款属于高风险商业安排，应另行审阅；本合成样本保留该不平衡表达用于系统识别。\n付款30%。'
    cleaned, removed = clean_text(source)
    assert '损失由供应方全部承担。' in cleaned
    assert '付款30%。' in cleaned
    assert '高风险' not in cleaned and '案例编号' not in cleaned
    assert removed


def test_budget_matched_control_has_same_calls_and_caps():
    assert arm_calls('S1') == [('general', 3200)]
    assert arm_calls('S2') == [('general', 1600), ('general', 1600)]
    assert arm_calls('D2') == [('legal', 1600), ('finance', 1600)]
    with pytest.raises(ValueError):
        arm_calls('other')


@pytest.mark.parametrize('value', ['{}', '{"risks":"x"}', '{"risks":[{"category":"legal"}]}'])
def test_malformed_output_is_not_a_success(value):
    with pytest.raises(ValueError):
        parse_output(value)


class Adapter:
    def __init__(self, responses):
        self.responses = iter(responses)

    def chat(self, *args, **kwargs):
        row = next(self.responses)
        if isinstance(row, Exception):
            raise row
        return SimpleNamespace(text=row, finish_reason='stop', prompt_tokens=10,
                               completion_tokens=5, model='test-only')


def test_partial_failure_preserves_findings_and_failed_denominator():
    text = '验收后支付120%。'
    body = json.dumps({'risks': [{'category': 'finance', 'quote': text,
                                 'issue': '比例超额', 'suggestion': '核对基数'}]})
    row = execute_arm(Adapter([body, RuntimeError('模拟失败')]), text, 'D2')
    assert row['status'] == 'partial_failed'
    assert len(row['risks']) == 1 and row['successful_calls'] == 1
    assert row['risks'][0]['quote_verified'] is True


def test_empty_quote_is_invalid():
    body = json.dumps({'risks': [{'category': 'legal', 'quote': '', 'issue': 'x', 'suggestion': 'x'}]})
    with pytest.raises(ValueError):
        parse_output(body)


def test_blind_review_does_not_leak_arm_or_role():
    rows, mapping = blind_rows([{'case_id': 'c', 'repeat': 1, 'arm': 'D2',
                                'risks': [{'agent': 'finance', 'category': 'finance',
                                           'quote': 'x', 'issue': 'y', 'suggestion': 'z'}]}])
    assert rows[0]['risks'][0].get('agent') is None
    assert 'arm' not in rows[0]
    assert mapping[rows[0]['blind_id']]['arm'] == 'D2'


def test_score_refuses_pending_human_labels():
    with pytest.raises(ValueError, match='复核'):
        score_review([], [], {}, [{'case_id': 'c', 'review_status': 'pending_human_review'}])


def test_score_missing_predictions_is_not_zero_accuracy():
    gold = [{'case_id': 'c', 'review_status': 'agreed', 'reviewers': ['a', 'b'],
             'risks': [{'risk_id': 'r1', 'category': 'finance'}]}]
    results, blind, mapping = [], [], {}
    for arm in ('S1', 'S2', 'D2'):
        for repeat in (1, 2, 3):
            identity = f'{arm}{repeat}'
            results.append({'case_id': 'c', 'arm': arm, 'repeat': repeat,
                            'risks': [], 'status': 'failed'})
            blind.append({'blind_id': identity, 'reviewers': ['a', 'b'],
                          'review_status': 'agreed', 'judgments': []})
            mapping[identity] = {'case_id': 'c', 'arm': arm, 'repeat': repeat}
    scored = score_review(results, blind, mapping, gold)
    assert scored['arms']['D2']['precision'] is None
    assert scored['arms']['D2']['recall'] == 0
    assert scored['arms']['D2']['fn'] == 3
    assert scored['arms']['D2']['success_rate'] == 0


def test_score_requires_each_planned_cell():
    gold = [{'case_id': 'c', 'review_status': 'agreed', 'reviewers': ['a', 'b'], 'risks': []}]
    with pytest.raises(ValueError, match='完整'):
        score_review([], [], {}, gold)


def test_docx_uses_inserted_revision_and_skips_deleted(tmp_path):
    from zipfile import ZipFile
    source = tmp_path / 'revision.docx'
    xml = '''<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>
      <w:p><w:r><w:t>有效正文</w:t></w:r></w:p>
      <w:p><w:del><w:r><w:delText>旧版无限责任</w:delText></w:r></w:del>
      <w:ins><w:r><w:t>新版合理责任</w:t></w:r></w:ins></w:p></w:body></w:document>'''
    with ZipFile(source, 'w') as z:
        z.writestr('word/document.xml', xml)
    extracted = extract_text(source)
    assert '新版合理责任' in extracted and '旧版无限责任' not in extracted


def test_cleaning_redacts_contact_for_all_arms():
    cleaned, _ = clean_text('联系人：合成测试员。付款30%。')
    from app.services.sensitive_data import contains_sensitive_data
    assert not contains_sensitive_data(cleaned)
    assert '付款30%' in cleaned


def test_technical_summary_never_invents_quality_scores():
    from evaluation.agent_comparison_report import technical_summary
    report = technical_summary([{'arm': 'D2', 'status': 'success', 'elapsed_ms': 10,
                                'calls': [{'status': 'success', 'prompt_tokens': 20, 'completion_tokens': 5}],
                                'risks': [{'quote_verified': True}]}])
    assert report['arms']['D2']['exact_quote_rate'] == 1
    assert report['arms']['D2']['risk_precision'] is None
    assert report['arms']['S1']['exact_quote_rate'] is None


def test_provider_reported_over_budget_usage_is_disclosed():
    from evaluation.agent_comparison_report import technical_summary
    report = technical_summary([{'arm': 'D2', 'status': 'success', 'elapsed_ms': 10,
                                'calls': [{'status': 'success', 'max_output_tokens': 1600,
                                           'prompt_tokens': 20, 'completion_tokens': 2371}], 'risks': []}])
    assert report['arms']['D2']['usage_exceeds_requested_cap_calls'] == 1


def test_unknown_usage_is_not_reported_as_measured_zero():
    from evaluation.agent_comparison_report import technical_summary
    report = technical_summary([{'arm': 'S1', 'status': 'failed', 'elapsed_ms': 10,
                                'calls': [{'status': 'failed', 'prompt_tokens': None,
                                           'completion_tokens': None}], 'risks': []}])
    assert report['arms']['S1']['unreported_usage_calls'] == 1
