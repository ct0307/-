"""LLM Adapter 的成本与协议约束。"""
import httpx
import pytest

from app.llm.base import LLMError
from app.llm.adapters.openai_compatible import OpenAICompatibleAdapter


class _Response:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {
            "model": "deepseek-v4-pro",
            "choices": [{"message": {"content": "{}"}, "finish_reason": "length"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 2},
        }


def test_chat_request_enforces_output_token_budget(monkeypatch):
    captured: dict = {}

    def fake_post(_url, *, json, headers, timeout):
        captured.update({"json": json, "headers": headers, "timeout": timeout})
        return _Response()

    monkeypatch.setattr("app.llm.adapters.openai_compatible.httpx.post", fake_post)
    adapter = OpenAICompatibleAdapter(
        base_url="https://llm.example/v1",
        api_key="test-only",
        model="deepseek-v4-pro",
        timeout=45,
        max_output_tokens=1600,
    )

    adapter.chat("system", "user")

    assert captured["json"]["max_tokens"] == 1600
    assert captured["json"]["stream"] is False
    assert captured["timeout"] == 45


def test_chat_response_exposes_finish_reason(monkeypatch):
    monkeypatch.setattr(
        "app.llm.adapters.openai_compatible.httpx.post",
        lambda *_args, **_kwargs: _Response(),
    )

    response = OpenAICompatibleAdapter(base_url="https://llm.example/v1").chat(
        "system", "user"
    )

    assert response.finish_reason == "length"


def test_http_error_log_does_not_include_provider_response_body(monkeypatch):
    from app.llm.adapters import openai_compatible

    events: list[tuple[str, dict]] = []
    response = httpx.Response(
        500,
        text="SENSITIVE-CONTRACT-CONTENT",
        headers={"x-ds-trace-id": "trace-123"},
        request=httpx.Request("POST", "https://llm.example/v1/chat/completions"),
    )

    monkeypatch.setattr(openai_compatible.httpx, "post", lambda *_args, **_kwargs: response)
    monkeypatch.setattr(
        openai_compatible.log,
        "error",
        lambda event, **fields: events.append((event, fields)),
    )
    adapter = OpenAICompatibleAdapter(
        base_url="https://llm.example/v1",
        api_key="test-only",
        model="deepseek-v4-pro",
    )

    with pytest.raises(LLMError):
        adapter.chat("system", "user")

    assert "SENSITIVE-CONTRACT-CONTENT" not in repr(events)
    assert events == [(
        "llm.http_error",
        {"path": "/chat/completions", "status": 500, "request_id": "trace-123"},
    )]


def test_network_error_does_not_expose_provider_exception(monkeypatch):
    from app.llm.adapters import openai_compatible

    events: list[tuple[str, dict]] = []
    request = httpx.Request("POST", "https://llm.example/v1/chat/completions")

    def fail_post(*_args, **_kwargs):
        raise httpx.ConnectError(
            "Authorization=Bearer sk-test-secret at db.internal",
            request=request,
        )

    monkeypatch.setattr(openai_compatible.httpx, "post", fail_post)
    monkeypatch.setattr(
        openai_compatible.log,
        "error",
        lambda event, **fields: events.append((event, fields)),
    )
    adapter = OpenAICompatibleAdapter(
        base_url="https://llm.example/v1",
        api_key="test-only",
        model="deepseek-v4-pro",
    )

    with pytest.raises(LLMError) as exc_info:
        adapter.chat("system", "user")

    assert "sk-test-secret" not in repr(events)
    assert "sk-test-secret" not in str(exc_info.value)
    assert events == [(
        "llm.request_error",
        {"path": "/chat/completions", "exception_type": "ConnectError"},
    )]
