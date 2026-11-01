"""AI复核的来源透明、覆盖完整性和不确定性保护。"""
import importlib
import json
from types import SimpleNamespace

import pytest


def module():
    return importlib.import_module('evaluation.agent_comparison_ai_review')


def annotation(quote='预付全部款项', status='supported'):
    return {'category': 'finance', 'quote': quote, 'issue': '预付款回收缺少保障',
            'reason': '履约前支付且未见担保', 'suggestion': '约定预付款担保',
            'severity': 'P2', 'status': status}


def test_unlocatable_reference_is_uncertain_not_verified_truth():
    m = module()
    result = m.validate_annotations({'risks': [annotation()]}, '验收后付尾款')
    assert result['risks'][0]['status'] == 'uncertain'
    assert result['risks'][0]['quote_verified'] is False


def test_empty_reference_quote_rejected():
    with pytest.raises(ValueError):
        module().validate_annotations({'risks': [annotation('')]}, '正文')


def test_pool_reuses_exact_finding_without_revealing_source_roles():
    finding = {'category': 'finance', 'quote': '款项', 'issue': 'x', 'suggestion': 'y'}
    blind = [{'blind_id': 'B1', 'case_id': 'c', 'risks': [finding]},
             {'blind_id': 'B2', 'case_id': 'c', 'risks': [{**finding, 'suggestion': 'z'}]}]
    pool, mapping = module().build_pool(blind)
    assert len(pool['c']) == 1
    assert mapping['B1'] == mapping['B2']
    assert not any(s in json.dumps(pool) for s in ('blind_id', 'arm', 'agents', 'repeat'))
    assert pool['c'][0]['prediction_id'].isalpha()


@pytest.mark.parametrize('judgments', [[],
    [{'prediction_id': 'p', 'status': 'match', 'reference_ids': ['unknown'], 'reason': '理由'}],
    [{'prediction_id': 'p', 'status': 'match', 'reference_ids': [], 'reason': '理由'}],
    [{'prediction_id': 'p', 'status': 'unsupported', 'reference_ids': ['r'], 'reason': '理由'}]])
def test_judgments_cannot_omit_or_invent_matches(judgments):
    with pytest.raises(ValueError):
        module().validate_judgments({'judgments': judgments}, ['p'], ['r'])


def test_new_supported_issue_remains_unresolved_not_false_positive():
    row = {'prediction_id': 'p', 'status': 'novel_supported', 'reference_ids': [], 'reason': '参考未收录'}
    assert module().validate_judgments({'judgments': [row]}, ['p'], []) == [row]


def test_coverage_deduplicates_matches_preserves_failed_samples_and_pending():
    m = module()
    references = [{'case_id': 'c', 'risks': [{'reference_id': 'r', **annotation()}]}]
    result_rows, blind, mapping, expanded = [], [], {}, []
    for repeat in (1, 2, 3):
        for arm in ('S1', 'S2', 'D2'):
            bid = arm + str(repeat)
            risks = [annotation(), annotation()] if repeat == 1 else []
            result_rows.append({'case_id': 'c', 'repeat': repeat, 'arm': arm,
                                'status': 'success' if risks else 'failed', 'risks': risks})
            blind.append({'blind_id': bid, 'case_id': 'c', 'risks': risks})
            mapping[bid] = {'case_id': 'c', 'repeat': repeat, 'arm': arm}
            expanded.append({'blind_id': bid, 'judgments': [
                {'finding_index': i, 'status': 'match', 'reference_ids': ['r'], 'reason': '相同问题'}
                for i in range(len(risks))]})
    scored = m.summarize(result_rows, blind, mapping, references, expanded)
    for arm in ('S1', 'S2', 'D2'):
        s = scored['arms'][arm]
        assert s['cells'] == 3 and s['matched_reference_instances'] == 1
        assert s['reference_duplicate_findings'] == 1
        assert s['ai_reference_coverage'] == pytest.approx(1/3)
        assert s['risk_precision'] is None and s['risk_f1'] is None
    assert scored['human_review_complete'] is False
    expanded[0]['judgments'][0].update(status='pending', reference_ids=[])
    incomplete = m.summarize(result_rows, blind, mapping, references, expanded)
    assert incomplete['arms']['S1']['ai_reference_coverage'] is None


def test_incomplete_cells_are_rejected_before_summary():
    with pytest.raises(ValueError):
        module().summarize([], [], {}, [{'case_id': 'c', 'risks': []}], [])


def test_retry_history_is_preserved_and_resume_does_not_call_again(tmp_path):
    m = module()
    class Adapter:
        calls = 0
        def chat(self, *args, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise TimeoutError('不得保存的服务错误原文')
            return SimpleNamespace(text='{}', finish_reason='stop', prompt_tokens=4,
                                   completion_tokens=2, model='test')
    adapter = Adapter()
    path = tmp_path / 'task.json'
    record = m.invoke(adapter, '任务', {'contract': '正文'}, lambda value: value, path)
    assert record['status'] == 'success' and len(record['attempts']) == 2
    assert record['attempts'][0]['prompt_tokens'] is None
    assert '不得保存' not in path.read_text(encoding='utf-8')
    m.invoke(adapter, '任务', {'contract': '正文'}, lambda value: value, path)
    assert adapter.calls == 2
    with pytest.raises(ValueError):
        m.invoke(adapter, '变更任务', {'contract': '正文'}, lambda value: value, path)


def test_ai_reference_is_not_accepted_as_human_gold():
    from evaluation.agent_comparison_score import score_review
    with pytest.raises(ValueError, match='复核'):
        score_review([], [], {}, [{'case_id': 'c', 'reviewer_type': 'ai_simulated_roles',
                                   'risks': [annotation()], 'human_review_complete': False}])


def test_report_refuses_unfinished_ai_review(tmp_path):
    reporter = importlib.import_module('evaluation.agent_comparison_ai_report')
    (tmp_path / 'review-run.json').write_text(json.dumps({'status': 'references_frozen'}), encoding='utf-8')
    with pytest.raises(ValueError, match='未完成'):
        reporter.build_documents(tmp_path, tmp_path, tmp_path)


def test_report_and_exports_keep_ai_provenance_and_all_findings(tmp_path):
    from docx import Document
    from evaluation.agent_comparison import digest, dump
    reporter = importlib.import_module('evaluation.agent_comparison_ai_report')
    m = module()
    for directory in ('role-annotations', 'consolidation', 'judgments'):
        (tmp_path / directory).mkdir()
    refs = [{'case_id': 'c', 'risks': [{'reference_id': 'r', **annotation()}], 'cleared_points': []}]
    dump(tmp_path / 'ai-reference-v1.json', refs)
    dump(tmp_path / 'review-run.json', {'status': 'ai_review_complete_pending_human',
        'reference_sha256': digest((tmp_path / 'ai-reference-v1.json').read_bytes()),
        'model': 'test-only', 'tasks': 3})
    dump(tmp_path / 'manifest.json', [{'case_id': 'c', 'source_file': '合同.docx', 'split': 'test'}])
    record = {'data': {'risks': [{**annotation(), 'quote_verified': True}]}, 'attempts': [
        {'status': 'success', 'prompt_tokens': 2, 'completion_tokens': 1}]}
    for role in ('legal', 'finance'):
        dump(tmp_path / 'role-annotations' / f'c-{role}.json', record)
    dump(tmp_path / 'consolidation' / 'c.json', record)
    blind, expanded, results, identities = [], [], [], {}
    for arm in ('S1', 'S2', 'D2'):
        for repeat in (1, 2, 3):
            bid = arm + str(repeat)
            identities[bid] = {'case_id': 'c', 'arm': arm, 'repeat': repeat}
            blind.append({'blind_id': bid, 'case_id': 'c', 'risks': [annotation()]})
            expanded.append({'blind_id': bid, 'judgments': [{'finding_index': 0,
                'status': 'match', 'reference_ids': ['r'], 'reason': '测试'}]})
            results.append({**identities[bid], 'status': 'success', 'risks': [annotation()]})
    dump(tmp_path / 'blind-review.json', blind)
    dump(tmp_path / 'private-unblind-map.json', identities)
    pool, _ = m.build_pool(blind)
    dump(tmp_path / 'prediction-pool.json', pool)
    dump(tmp_path / 'ai-blind-review.json', expanded)
    dump(tmp_path / 'unresolved-candidates.json', [])
    dump(tmp_path / 'ai-summary.json', m.summarize(results, blind, identities, refs, expanded))
    report = reporter.build_documents(tmp_path, tmp_path, tmp_path)
    assert report['role_annotation_rows'] == 2
    assert report['finding_judgment_rows'] == 9
    text = '\n'.join(p.text for p in Document(report['report']).paragraphs)
    assert '不是真人专家金标' in text and '法律准确率' in text
