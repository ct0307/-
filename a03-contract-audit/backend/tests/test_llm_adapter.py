"""LLM Adapter 的成本与协议约束。"""
import copy
from dataclasses import asdict
import pickle
import sys
import traceback
import types

import httpx
import pytest

from app.llm.base import ChatOptions, LLMError
from app.llm.adapters.local_embedding import LocalEmbeddingAdapter
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
    assert exc_info.value.code == "MODEL_UNAVAILABLE"
    assert exc_info.value.retryable is True
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__context__ is None
    assert "sk-test-secret" not in "".join(traceback.format_exception(exc_info.value))
    assert events == [(
        "llm.request_error",
        {"path": "/chat/completions", "exception_type": "ConnectError"},
    )]


def test_chat_options_override_budget_and_add_structured_request_fields(monkeypatch):
    captured: dict = {}

    def fake_post(_url, *, json, headers, timeout):
        captured.update({"json": json, "headers": headers, "timeout": timeout})
        return _Response()

    monkeypatch.setattr("app.llm.adapters.openai_compatible.httpx.post", fake_post)
    adapter = OpenAICompatibleAdapter(
        base_url="https://llm.example/v1",
        api_key="test-only",
        model="deepseek-v4-pro",
        max_output_tokens=1600,
    )

    adapter.chat(
        "system",
        "user",
        options=ChatOptions(
            max_output_tokens=320,
            response_format={"type": "json_object"},
            request_id="request-123",
        ),
    )

    assert captured["json"]["max_tokens"] == 320
    assert captured["json"]["response_format"] == {"type": "json_object"}
    assert captured["headers"]["X-Request-ID"] == "request-123"


@pytest.mark.parametrize("max_output_tokens", [0, -1])
def test_chat_options_reject_non_positive_output_token_budget(max_output_tokens):
    adapter = OpenAICompatibleAdapter(base_url="https://llm.example/v1")

    with pytest.raises(ValueError, match="max_output_tokens"):
        adapter.chat(
            "system",
            "user",
            options=ChatOptions(max_output_tokens=max_output_tokens),
        )


def test_timeout_is_a_safe_structured_retryable_error(monkeypatch):
    from app.llm.adapters import openai_compatible

    request = httpx.Request("POST", "https://llm.example/v1/chat/completions")

    def fail_post(*_args, **_kwargs):
        raise httpx.ReadTimeout(
            "Authorization=Bearer sk-test-secret timed out",
            request=request,
        )

    monkeypatch.setattr(openai_compatible.httpx, "post", fail_post)
    adapter = OpenAICompatibleAdapter(
        base_url="https://llm.example/v1",
        api_key="test-only",
        model="deepseek-v4-pro",
    )

    with pytest.raises(LLMError) as exc_info:
        adapter.chat("system", "user")

    assert exc_info.value.code == "MODEL_TIMEOUT"
    assert exc_info.value.retryable is True
    assert "sk-test-secret" not in str(exc_info.value)
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__context__ is None
    assert "sk-test-secret" not in "".join(traceback.format_exception(exc_info.value))


@pytest.mark.parametrize(
    ("status", "retryable"),
    [(400, False), (408, True), (429, True), (500, True)],
)
def test_http_status_errors_have_safe_retry_policy(monkeypatch, status, retryable):
    from app.llm.adapters import openai_compatible

    response = httpx.Response(
        status,
        text="SENSITIVE-CONTRACT-CONTENT",
        request=httpx.Request("POST", "https://llm.example/v1/chat/completions"),
    )
    monkeypatch.setattr(openai_compatible.httpx, "post", lambda *_args, **_kwargs: response)

    with pytest.raises(LLMError) as exc_info:
        OpenAICompatibleAdapter(base_url="https://llm.example/v1").chat("system", "user")

    assert exc_info.value.code == "MODEL_REJECTED"
    assert exc_info.value.retryable is retryable
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__context__ is None
    assert "SENSITIVE-CONTRACT-CONTENT" not in "".join(traceback.format_exception(exc_info.value))


def test_invalid_json_response_is_a_safe_structured_error(monkeypatch):
    from app.llm.adapters import openai_compatible

    class InvalidJsonResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            raise ValueError("SENSITIVE-CONTRACT-CONTENT sk-test-secret")

    monkeypatch.setattr(
        openai_compatible.httpx,
        "post",
        lambda *_args, **_kwargs: InvalidJsonResponse(),
    )

    with pytest.raises(LLMError) as exc_info:
        OpenAICompatibleAdapter(base_url="https://llm.example/v1").chat("system", "user")

    assert exc_info.value.code == "MODEL_UNAVAILABLE"
    assert exc_info.value.retryable is True
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__context__ is None
    formatted = "".join(traceback.format_exception(exc_info.value))
    assert "SENSITIVE-CONTRACT-CONTENT" not in formatted
    assert "sk-test-secret" not in formatted


def test_local_embedding_errors_do_not_retain_sensitive_exception_chain(monkeypatch):
    class FailingSentenceTransformer:
        def __init__(self, *_args, **_kwargs) -> None:
            raise RuntimeError("SENSITIVE-CONTRACT-CONTENT sk-test-secret")

    module = types.ModuleType("sentence_transformers")
    module.SentenceTransformer = FailingSentenceTransformer
    monkeypatch.setitem(sys.modules, "sentence_transformers", module)

    with pytest.raises(LLMError) as exc_info:
        LocalEmbeddingAdapter("test-model").embed(["test"])

    assert exc_info.value.__cause__ is None
    assert exc_info.value.__context__ is None
    formatted = "".join(traceback.format_exception(exc_info.value))
    assert "SENSITIVE-CONTRACT-CONTENT" not in formatted
    assert "sk-test-secret" not in formatted


def test_chat_options_defensively_copy_response_format_for_serialization():
    response_format = {"type": "json_object"}
    options = ChatOptions(response_format=response_format)
    response_format["type"] = "text"

    serialized = asdict(options)

    assert options.response_format == {"type": "json_object"}
    assert isinstance(options.response_format, dict)
    assert serialized["response_format"] == {"type": "json_object"}
    assert type(serialized["response_format"]) is dict


@pytest.mark.parametrize(
    "mutation",
    [
        lambda response_format: response_format.__setitem__("type", "text"),
        lambda response_format: response_format.update({"type": "text"}),
        lambda response_format: response_format.pop("type"),
    ],
)
def test_chat_options_response_format_rejects_mutation(mutation):
    options = ChatOptions(response_format={"type": "json_object"})

    assert options.response_format is not None
    with pytest.raises(TypeError, match="immutable"):
        mutation(options.response_format)


def test_chat_options_response_format_rejects_reinitialization():
    options = ChatOptions(response_format={"type": "json_object"})

    assert options.response_format is not None
    with pytest.raises(TypeError, match="immutable"):
        options.response_format.__init__({"type": "mutated"})

    assert options.response_format == {"type": "json_object"}


def test_chat_options_rejects_non_dict_response_format():
    with pytest.raises(TypeError, match="response_format must be a dict"):
        ChatOptions(response_format=(("type", "json_object"),))


@pytest.mark.parametrize("clone", [copy.deepcopy, lambda options: pickle.loads(pickle.dumps(options))])
def test_chat_options_clones_preserve_immutable_response_format(clone):
    cloned = clone(ChatOptions(response_format={"type": "json_object"}))

    assert cloned.response_format == {"type": "json_object"}
    assert isinstance(cloned.response_format, dict)
    assert cloned.response_format is not None
    with pytest.raises(TypeError, match="immutable"):
        cloned.response_format.update({"type": "mutated"})


def test_local_request_value_error_is_not_mapped_to_model_unavailable(monkeypatch):
    from app.llm.adapters import openai_compatible

    def fail_post(*_args, **_kwargs):
        raise ValueError("temperature must be finite")

    monkeypatch.setattr(openai_compatible.httpx, "post", fail_post)

    with pytest.raises(ValueError, match="temperature must be finite"):
        OpenAICompatibleAdapter(base_url="https://llm.example/v1").chat("system", "user")


def test_empty_optional_protocol_fields_are_not_sent(monkeypatch):
    captured: dict = {}

    def fake_post(_url, *, json, headers, timeout):
        captured.update({"json": json, "headers": headers, "timeout": timeout})
        return _Response()

    monkeypatch.setattr("app.llm.adapters.openai_compatible.httpx.post", fake_post)

    OpenAICompatibleAdapter(base_url="https://llm.example/v1").chat(
        "system",
        "user",
        options=ChatOptions(response_format={}, request_id=""),
    )

    assert "response_format" not in captured["json"]
    assert "X-Request-ID" not in captured["headers"]
