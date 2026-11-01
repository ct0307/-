"""验证真实审查各入口的范围数据，防止子窗口冒充全文。"""
import json

from app.services.audit import auditor
from app.services.audit.protocol import AgentReviewResult, RiskFinding
from app.services.audit.review_pipeline import ReviewWindow
from app.services.rag.contract_structure import ContractWindow


def _requests(monkeypatch, text):
    captured = []
    monkeypatch.setattr(auditor, 'retrieve', lambda *_args, **_kwargs: [])
    def review(requests, **_kwargs):
        captured.extend(requests)
        return [AgentReviewResult(complete=True) for _ in requests]
    monkeypatch.setattr(auditor, '_review_window_requests', review)
    auditor._agent_audit('legal', {}, text, {}, dimensions=[], adapter_factory=lambda: None)
    return captured


def _scope(prompt):
    start = prompt.index('<review_scope>') + len('<review_scope>')
    return json.loads(prompt[start:prompt.index('</review_scope>')])


def test_all_prompt_entries_receive_full_text_scope_and_master_reference(monkeypatch):
    text = '第一条 付款\n出库前付清。\n第二条 适用文件\n本订单按《供货主协议》执行，主协议另附。'
    request = _requests(monkeypatch, text)[0]
    finding = RiskFinding(level='medium', category='付款风险', quote='出库前付清。')
    window = request.review_window
    prompts = [request.build_user_prompt(window, 1, ()),
               request.build_discovery_prompt(window, 1, (), (), 5),
               request.build_enrichment_prompt(window, finding, False),
               request.build_enrichment_batch_prompt(window, (finding,), False)]
    for prompt in prompts:
        scope = _scope(prompt)
        assert scope['window_covers_full_text'] is True
        assert scope['whole_contract_characters'] == len(text)
        assert any('《供货主协议》' in item for item in scope['referenced_document_clues'])


def test_split_recovery_recalculates_scope_for_actual_subwindow(monkeypatch):
    text = '第一条 付款\n出库前付清。\n第二条 争议解决\n争议由合同签订地法院管辖。'
    request = _requests(monkeypatch, text)[0]
    child = ReviewWindow(ContractWindow('child', ('第一条',), '第一条 付款\n出库前付清。'), depth=1)
    finding = RiskFinding(level='medium', category='付款风险', quote='出库前付清。')
    for prompt in [request.build_user_prompt(child, 1, ()),
                   request.build_discovery_prompt(child, 1, (), (), 5),
                   request.build_enrichment_prompt(child, finding, False),
                   request.build_enrichment_batch_prompt(child, (finding,), False)]:
        scope = _scope(prompt)
        assert scope['window_covers_full_text'] is False
        assert scope['window_characters'] < scope['whole_contract_characters']
        assert any('争议解决' in item for item in scope['whole_contract_outline'])


def test_long_contract_scope_is_bounded_without_claiming_full_outline(monkeypatch):
    text = '\n'.join(f'第{i}条 条款{i}\n付款按订单约定。' for i in range(1, 85))
    request = _requests(monkeypatch, text)[0]
    scope = _scope(request.build_user_prompt(request.review_window, 1, ()))
    assert len(scope['whole_contract_outline']) <= 60
    assert scope['outline_truncated'] is True
