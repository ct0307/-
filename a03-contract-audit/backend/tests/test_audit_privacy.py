"""审查外部模型边界：已知敏感字段不出站，原文引用仍可验证。"""
import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.llm.base import LLMError, LLMResponse
from app.services.sensitive_data import contains_sensitive_data


def privacy_adapter(adapter):
    from app.services.audit.privacy import AuditPrivacyAdapter
    return AuditPrivacyAdapter(adapter)


def test_redacts_nested_input_and_repeated_party_before_network_and_restores_quote():
    quote = '甲方：演示采购公司，联系人：张测试，电话13812345678，演示采购公司须先付全款。'
    request = {'contract_text': quote, 'elements': {'party': '演示采购公司'}, 'candidates': [quote]}

    class Echo:
        def chat(self, system, user, **kwargs):
            assert not contains_sensitive_data([system, user])
            assert '演示采购公司' not in user
            assert '13812345678' not in user
            assert '张测试' not in user
            data = json.loads(user)
            return LLMResponse(text=json.dumps({'quote': data['contract_text'], 'more': [data['elements']['party']]}, ensure_ascii=False), model='fake', prompt_tokens=17)

    response = privacy_adapter(Echo()).chat('仅返回JSON', json.dumps(request, ensure_ascii=False))
    result = json.loads(response.text)
    assert result == {'quote': quote, 'more': ['演示采购公司']}
    assert response.prompt_tokens == 17
    from app.services.audit.auditor import _verify_original_text
    assert _verify_original_text(result['quote'], quote) is True


def test_json_escaping_and_unknown_tokens_are_not_reinterpreted():
    quote = '邮箱test@example.com，联系人：测试\\账户，必须付款。'

    class Echo:
        def chat(self, system, user, **kwargs):
            return LLMResponse(text=json.dumps({'quote': user, 'unknown': '【隐私_其他请求_甲方】'}), model='fake')

    result = json.loads(privacy_adapter(Echo()).chat('JSON', quote).text)
    assert result['quote'] == quote
    assert result['unknown'] == '【隐私_其他请求_甲方】'
    from app.services.audit.auditor import _verify_original_text
    assert _verify_original_text(result['unknown'], quote) is False


def test_mapping_is_isolated_per_request_and_invalid_json_stays_invalid():
    seen = []

    class Echo:
        def chat(self, system, user, **kwargs):
            seen.append(user)
            return LLMResponse(text=json.dumps({'quote': user}), model='fake')

    adapter = privacy_adapter(Echo())
    texts = ['甲方：测试公司甲，须付款。', '甲方：测试公司乙，须付款。']
    with ThreadPoolExecutor(max_workers=2) as pool:
        outputs = list(pool.map(lambda text: json.loads(adapter.chat('JSON', text).text)['quote'], texts))
    assert outputs == texts
    assert seen[0] != seen[1]

    class Invalid:
        def chat(self, *args, **kwargs):
            return LLMResponse(text='```json\n{}\n```', model='fake')
    assert privacy_adapter(Invalid()).chat('JSON', texts[0]).text == '```json\n{}\n```'


def test_wrapped_adapter_keeps_endpoint_guard(monkeypatch):
    from app.llm.adapters.openai_compatible import OpenAICompatibleAdapter, settings
    monkeypatch.setattr(settings, 'MODEL_PROCESSING_MODE', 'external_model')
    monkeypatch.setattr(settings, 'MODEL_EXTERNAL_ALLOWED_BASE_URLS', ['https://approved.example/v1'])
    with pytest.raises(LLMError) as caught:
        privacy_adapter(OpenAICompatibleAdapter(base_url='https://unapproved.example/v1')).chat('JSON', '甲方：测试公司，须付款。')
    assert caught.value.code == 'MODEL_OUTBOUND_BLOCKED'


def test_later_window_masks_known_party_without_repeating_the_label():
    from app.services.audit.privacy import AuditPrivacyAdapter
    class Echo:
        def chat(self, system, user, **kwargs):
            assert '演示采购公司' not in user
            return LLMResponse(text=json.dumps({'quote': user}), model='fake')
    adapter = AuditPrivacyAdapter(Echo(), context='甲方：演示采购公司\n乙方：演示供货公司', elements={'party_a': '演示采购公司'})
    quote = '演示采购公司须付款。'
    assert json.loads(adapter.chat('JSON', quote).text)['quote'] == quote


def test_blank_party_labels_do_not_create_empty_replacement_or_expand_plain_text():
    class Echo:
        def chat(self, system, user, **kwargs):
            assert user == '请检查付款条款。'
            return LLMResponse(text='{"risks": [], "has_more": false}', model='fake')
    from app.services.audit.privacy import AuditPrivacyAdapter
    adapter = AuditPrivacyAdapter(Echo(), context='甲方：     ，乙方：示例公司。')
    adapter.chat('JSON', '请检查付款条款。')


@pytest.mark.parametrize('separator', [' ', ''])
def test_inline_labels_mask_each_atomic_value_and_unlabelled_repetition(separator):
    from app.services.audit.privacy import AuditPrivacyAdapter
    text = f'甲方：演示公司{separator}联系人：张测试\n演示公司代表张测试须付款。'
    class Echo:
        def chat(self, system, user, **kwargs):
            assert '演示公司' not in user
            assert '张测试' not in user
            return LLMResponse(text=json.dumps({'quote': user}), model='fake')
    result = AuditPrivacyAdapter(Echo(), context=text, elements={'party_a': '演示公司'}).chat('JSON', text)
    assert json.loads(result.text)['quote'] == text


@pytest.mark.parametrize('separator', ['\n', '\r\n  ', '\t'])
def test_multiline_labels_seed_unlabelled_later_windows(separator):
    from app.services.audit.privacy import AuditPrivacyAdapter
    context = f'甲方：{separator}演示公司\n联系人：{separator}张测试'
    quote = '演示公司代表张测试须付款。'
    class Echo:
        def chat(self, system, user, **kwargs):
            assert '演示公司' not in user
            assert '张测试' not in user
            return LLMResponse(text=json.dumps({'quote': user}), model='fake')
    result = AuditPrivacyAdapter(Echo(), context=context, elements={'party_a': '演示公司'}).chat('JSON', quote)
    assert json.loads(result.text)['quote'] == quote
