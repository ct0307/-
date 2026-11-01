from app.services.masking import apply_risk_masking, mask_original_text


def test_short_sensitive_fields_and_nested_outputs_are_masked_without_mutating_input():
    text = '手机13812345678，身份证110101199001011234，账号6222021234567890123，邮箱test@example.com'
    assert '13812345678' not in mask_original_text(text)
    original = {'original_text': text, 'suggestion': text, 'risk_reason': text,
                'decision_trace': {'human_review': {'reason': text}}}
    result = apply_risk_masking(original, 'business')
    assert '13812345678' not in str(result)
    assert result['decision_trace']['human_review']['reason'] != text
    assert original['suggestion'] == text
    assert apply_risk_masking(original, 'legal') == original


def test_external_payload_guard_rejects_sensitive_chat_and_embedding_before_network(monkeypatch):
    import pytest
    from app.llm.adapters import openai_compatible as adapter
    from app.llm.base import LLMError
    monkeypatch.setattr(adapter.settings, 'MODEL_PROCESSING_MODE', 'external_model')
    monkeypatch.setattr(adapter.settings, 'MODEL_EXTERNAL_ALLOWED_BASE_URLS', ['https://approved.example/v1'], raising=False)
    monkeypatch.setattr(adapter.httpx, 'post', lambda *a, **k: pytest.fail('敏感字段不得外传'))
    client = adapter.OpenAICompatibleAdapter(base_url='https://approved.example/v1')
    for call in (lambda: client.chat('system', '联系人13812345678'),
                 lambda: client.embed(['账号6222021234567890123'])):
        with pytest.raises(LLMError) as error:
            call()
        assert error.value.code == 'MODEL_OUTBOUND_BLOCKED'


def test_external_destination_requires_explicit_https_authorization():
    import pytest
    from types import SimpleNamespace
    from app.core.model_policy import check_model_endpoint
    config = SimpleNamespace(MODEL_PROCESSING_MODE='external_model', MODEL_EXTERNAL_ALLOWED_BASE_URLS=['https://approved.example/v1'])
    check_model_endpoint('https://approved.example/v1', config)
    for url in ('https://other.example/v1', 'https://approved.example.evil/v1',
                'http://approved.example/v1', 'https://approved.example/v1?x=1'):
        with pytest.raises(ValueError):
            check_model_endpoint(url, config)


def test_long_plain_text_does_not_trigger_unbounded_regex_backtracking():
    import subprocess
    import sys
    # 子进程超时保护：错误正则不能卡死整个测试进程。
    subprocess.run([sys.executable, '-c',
        "from app.services.sensitive_data import redact_sensitive_text, contains_sensitive_data; "
        "text='x'*100000; assert redact_sensitive_text(text)==text; assert not contains_sensitive_data(text)"],
        check=True, timeout=3, capture_output=True)
