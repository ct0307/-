from fastapi.testclient import TestClient
import pytest

from app import main as main_module
from app.core.config import (
    Settings,
    llm_configuration_metadata,
    validate_llm_configuration,
)
from app.main import app
from app.api.v1.endpoints.runtime import PublicRuntimeStatus


client = TestClient(app)


def test_live_health_is_public_and_reports_process_liveness():
    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_ready_health_returns_200_when_dependencies_are_ready(monkeypatch):
    monkeypatch.setattr(
        "app.main.collect_readiness",
        lambda **_kwargs: {"database": {"ready": True}, "model": {"ready": True}},
    )

    response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"


def test_ready_health_returns_503_with_safe_failure_code(monkeypatch):
    monkeypatch.setattr(
        "app.main.collect_readiness",
        lambda **_kwargs: {
            "database": {"ready": True},
            "model": {"ready": False, "error_code": "auth_failed"},
        },
    )

    response = client.get("/health/preflight")

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "checks": {
            "database": {"ready": True},
            "model": {"ready": False, "error_code": "auth_failed"},
        },
    }


def test_ready_health_keeps_instance_ready_when_model_is_degraded(monkeypatch):
    monkeypatch.setattr(
        "app.main.collect_readiness",
        lambda **_kwargs: {
            "database": {"ready": True},
            "model": {"ready": False, "error_code": "network_error"},
        },
    )

    response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert response.json()["checks"]["model"]["error_code"] == "network_error"


def test_ready_health_returns_503_when_database_is_unavailable(monkeypatch):
    monkeypatch.setattr(
        "app.main.collect_readiness",
        lambda **_kwargs: {
            "database": {"ready": False, "error_code": "database_unavailable"},
            "model": {"ready": True, "status": "online"},
        },
    )

    response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"


def test_ready_health_does_not_refresh_external_model(monkeypatch):
    calls: list[dict] = []

    def collect(**kwargs):
        calls.append(kwargs)
        return {
            "database": {"ready": True},
            "model": {"ready": False, "status": "checking", "error_code": "probe_pending"},
        }

    monkeypatch.setattr("app.main.collect_readiness", collect)

    response = client.get("/health/ready")

    assert response.status_code == 200
    assert calls == [{"refresh_model": False}]


def test_preflight_requires_model_readiness(monkeypatch):
    monkeypatch.setattr(
        "app.main.collect_readiness",
        lambda: {
            "database": {"ready": True},
            "model": {"ready": False, "error_code": "timeout"},
        },
    )

    response = client.get("/health/preflight")

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"


def test_deepseek_configuration_requires_api_key():
    config = Settings(
        _env_file=None,
        LLM_PROVIDER="deepseek",
        LLM_BASE_URL="https://api.deepseek.com/v1",
        LLM_MODEL="deepseek-v4-pro",
        LLM_API_KEY="",
    )

    with pytest.raises(ValueError, match="LLM_API_KEY"):
        validate_llm_configuration(config)


def test_model_configuration_requires_model_name():
    config = Settings(
        _env_file=None,
        LLM_PROVIDER="qwen",
        LLM_BASE_URL="http://localhost:11434/v1",
        LLM_MODEL=" ",
    )

    with pytest.raises(ValueError, match="LLM_MODEL"):
        validate_llm_configuration(config)


def test_model_configuration_metadata_is_stable_and_redacted():
    config = Settings(
        _env_file=None,
        LLM_PROVIDER="deepseek",
        LLM_BASE_URL="https://user:secret@api.deepseek.com/v1?token=private",
        LLM_MODEL="deepseek-v4-pro",
        LLM_API_KEY="test-secret-key",
    )

    metadata = llm_configuration_metadata(config)

    assert metadata["llm_provider"] == "deepseek"
    assert metadata["llm_model"] == "deepseek-v4-pro"
    assert metadata["llm_endpoint"] == "https://api.deepseek.com"
    assert len(metadata["llm_config_fingerprint"]) == 12
    assert "secret" not in repr(metadata)
    assert "private" not in repr(metadata)


def test_readiness_reuses_runtime_cache(monkeypatch):
    calls: list[dict] = []

    def cached_status(**kwargs):
        calls.append(kwargs)
        return PublicRuntimeStatus(status="online", checked_at="2026-09-11T10:00:00Z")

    monkeypatch.setattr(main_module, "_get_cached_runtime_status", cached_status)

    checks = main_module.collect_readiness()

    assert checks["model"]["ready"] is True
    assert calls == [{}]
