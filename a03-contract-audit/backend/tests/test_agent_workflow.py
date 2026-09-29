"""工作流行为反例：保留观点、复查不提升证据、预算阻断。"""
import json
from types import SimpleNamespace
import pytest
from app.llm.base import LLMError, LLMResponse
from app.services.audit.workflow import group_risks, directed_review, AuditBudget, BudgetAdapter


def candidates():
    return [dict(claim_id='a', agent='legal', category='付款期限', original_text='验收后付款', level='high'),
            dict(claim_id='b', agent='finance', category='付款期限', original_text='验收后付款', level='medium'),
            dict(claim_id='c', agent='finance', category='发票', original_text='验收后付款', level='low')]


def test_grouping_preserves_views_and_separates_distinct_issues():
    groups = group_risks(candidates())
    assert len(groups) == 2
    assert groups[0]['claim_ids'] == ['a', 'b']
    assert groups[0]['level'] == 'high'
    assert groups[0]['agents'] == ['finance', 'legal']
    assert group_risks(list(reversed(candidates())))[1]['issue_id'] == groups[0]['issue_id']


def test_directed_review_executes_target_role_once_and_keeps_machine_evidence():
    seen = []
    class Adapter:
        def chat(self, system, user, **kwargs):
            seen.append(json.loads(user))
            return LLMResponse(json.dumps({'verdict':'agree', 'claim_ids':['a'], 'quote':'验收后付款'}), 'test')
    risks = candidates()
    checks = [dict(id='X1', to='finance', trigger='付款复核', claim_ids=['a'])]
    results = directed_review(risks, checks, Adapter(), contract_text='合同约定验收后付款', max_calls=1)
    assert seen[0]['target_agent'] == 'finance'
    assert results[0]['status'] == 'reviewed'
    assert results[0]['verdict'] == 'agree'
    assert 'evidence_status' not in risks[0]


@pytest.mark.parametrize('payload', [
    {'verdict':'agree','claim_ids':['foreign'],'quote':'验收后付款'},
    {'verdict':'agree','claim_ids':['a'],'quote':'伪造原文'},
])
def test_invalid_directed_output_requires_manual_review(payload):
    adapter = SimpleNamespace(chat=lambda *a, **k: LLMResponse(json.dumps(payload), 'test'))
    checks = [dict(id='X1', to='finance', trigger='付款复核', claim_ids=['a'])]
    assert directed_review(candidates(), checks, adapter, contract_text='验收后付款')[0]['status'] == 'manual_required'


def test_budget_counts_failed_calls_and_blocks_before_next_network_request():
    calls = []
    def chat(*a, **k):
        calls.append(1)
        raise LLMError('服务不可用')
    budget = AuditBudget(max_calls=1, max_tokens=10000)
    adapter = BudgetAdapter(SimpleNamespace(chat=chat), budget)
    with pytest.raises(LLMError): adapter.chat('系统', '合同')
    with pytest.raises(LLMError) as exc: adapter.chat('系统', '合同')
    assert exc.value.retryable is False
    assert len(calls) == 1


def test_directed_limit_keeps_unexecuted_checks_as_manual_tasks():
    adapter = SimpleNamespace(chat=lambda *a, **k: pytest.fail('预算为零不能调用模型'))
    rows = directed_review(candidates(), [dict(id='X1',to='finance',claim_ids=['a'])], adapter,
                           contract_text='验收后付款', max_calls=0)
    assert rows[0]['status'] == 'manual_required'
    assert rows[0]['reason_code'] == 'DIRECTED_BUDGET_EXHAUSTED'


def test_directed_review_requires_original_text_for_every_candidate():
    adapter = SimpleNamespace(chat=lambda *a, **k: pytest.fail('任一候选缺少原文不能调用模型'))
    risks = candidates()
    risks[1]['original_text'] = '不在合同里的原文'
    rows = directed_review(risks, [dict(id='X1', to='finance', claim_ids=['a', 'b'])], adapter,
                           contract_text='验收后付款')
    assert rows[0]['status'] == 'manual_required'


def test_checkpoint_identity_changes_with_prompt_and_run_version():
    from app.services.audit.window_repository import SqlAlchemyWindowCheckpoint
    window = SimpleNamespace(window_id='w1', text='合同正文')
    request = SimpleNamespace(contract_id=1, audit_job_id=2, audit_generation=1, agent='legal',
                              dimensions=('legal',), review_window=SimpleNamespace(window=window),
                              system_prompt='初始提示词', discovery_system_prompt=None,
                              build_user_prompt=lambda *args: '合同上下文',
                              enrichment_system_prompt=None, run_fingerprint='version1')
    checkpoint = SqlAlchemyWindowCheckpoint()
    original = checkpoint._identity(request)
    request.system_prompt = '新的提示词'
    assert checkpoint._identity(request) != original
    request.system_prompt = '初始提示词'
    request.run_fingerprint = 'version2'
    assert checkpoint._identity(request) != original


def test_checkpoint_identity_changes_when_reference_context_changes():
    from app.services.audit.window_repository import SqlAlchemyWindowCheckpoint
    from app.services.audit.review_pipeline import WindowReviewRequest, ReviewWindow
    from app.services.rag.contract_structure import ContractWindow
    context = ['原参考资料']
    request = WindowReviewRequest(
        contract_id=1, audit_job_id=2, audit_generation=1, agent='legal', dimensions=('payment',),
        review_window=ReviewWindow(ContractWindow('w1', (), '合同原文')),
        system_prompt='固定提示词', build_user_prompt=lambda *args: context[0],
    )
    checkpoint = SqlAlchemyWindowCheckpoint()
    original = checkpoint._identity(request)
    context[0] = '更新后的合同要素和参考资料'
    assert checkpoint._identity(request) != original
