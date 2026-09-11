from fastapi.testclient import TestClient
import pytest

from app.core.config import Settings, validate_llm_configuration
from app.main import app


client = TestClient(app)


def test_live_health_is_public_and_reports_process_liveness():
    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_ready_health_returns_200_when_dependencies_are_ready(monkeypatch):
    monkeypatch.setattr(
        "app.main.collect_readiness",
        lambda: {"database": {"ready": True}, "model": {"ready": True}},
    )

    response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"


def test_ready_health_returns_503_with_safe_failure_code(monkeypatch):
    monkeypatch.setattr(
        "app.main.collect_readiness",
        lambda: {
            "database": {"ready": True},
            "model": {"ready": False, "error_code": "auth_failed"},
        },
    )

    response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "checks": {
            "database": {"ready": True},
            "model": {"ready": False, "error_code": "auth_failed"},
        },
    }


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
