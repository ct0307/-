import httpx
import pytest

from evaluation import runtime_client


def _response(status: int, payload: dict | None = None) -> httpx.Response:
    return httpx.Response(
        status,
        json=payload or {},
        request=httpx.Request("GET", "https://api.deepseek.com/v1/models"),
    )


def test_probe_retries_transient_connection_error(monkeypatch):
    calls = 0

    def fake_get(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ConnectError("private details", request=_kwargs.get("request") or httpx.Request("GET", "https://api.deepseek.com/v1/models"))
        return _response(200, {"data": [{"id": "deepseek-v4-pro"}]})

    monkeypatch.setattr(runtime_client.httpx, "get", fake_get)
    monkeypatch.setattr(runtime_client.settings, "LLM_BASE_URL", "https://api.deepseek.com/v1")
    monkeypatch.setattr(runtime_client.settings, "LLM_API_KEY", "test-key")
    monkeypatch.setattr(runtime_client.settings, "LLM_MODEL", "deepseek-v4-pro")

    assert runtime_client.probe_configured_model() == {"model": "deepseek-v4-pro"}
    assert calls == 2


@pytest.mark.parametrize(
    ("status", "error_code"),
    [(401, "auth_failed"), (403, "auth_failed"), (404, "endpoint_not_found")],
)
def test_probe_maps_http_errors(status, error_code, monkeypatch):
    monkeypatch.setattr(runtime_client.httpx, "get", lambda *_args, **_kwargs: _response(status))

    with pytest.raises(Exception) as exc_info:
        runtime_client.probe_configured_model()

    assert getattr(exc_info.value, "error_code", None) == error_code


def test_probe_reports_model_not_found(monkeypatch):
    monkeypatch.setattr(
        runtime_client.httpx,
        "get",
        lambda *_args, **_kwargs: _response(200, {"data": [{"id": "other-model"}]}),
    )
    monkeypatch.setattr(runtime_client.settings, "LLM_MODEL", "deepseek-v4-pro")

    with pytest.raises(Exception) as exc_info:
        runtime_client.probe_configured_model()

    assert getattr(exc_info.value, "error_code", None) == "model_not_found"
