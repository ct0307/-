from types import SimpleNamespace
import pytest


def test_private_mode_blocks_public_and_named_hosts():
    from app.core.model_policy import check_model_endpoint
    config = SimpleNamespace(MODEL_PROCESSING_MODE="private_model")
    for endpoint in ("https://api.example.com/v1", "https://8.8.8.8/v1", "https://localhost.evil/v1"):
        with pytest.raises(ValueError):
            check_model_endpoint(endpoint, config)
    check_model_endpoint("http://127.0.0.1:11434/v1", config)
    check_model_endpoint("http://192.168.1.8:8000/v1", config)


def test_rules_only_blocks_all_model_requests():
    from app.core.model_policy import check_model_endpoint
    with pytest.raises(ValueError):
        check_model_endpoint("http://127.0.0.1/v1", SimpleNamespace(MODEL_PROCESSING_MODE="rules_fallback"))


def test_rules_mode_can_start_without_model_credentials():
    from app.core.config import Settings, validate_llm_configuration, llm_configuration_metadata
    config = Settings(_env_file=None, MODEL_PROCESSING_MODE="rules_fallback", LLM_API_KEY="")
    validate_llm_configuration(config)
    assert llm_configuration_metadata(config)["llm_model"] == "disabled"


def test_runtime_probe_enforces_outbound_policy_before_network(monkeypatch):
    from evaluation import runtime_client
    from app.services.runtime.status import RuntimeProbeError
    monkeypatch.setattr(runtime_client.settings, "MODEL_PROCESSING_MODE", "rules_fallback")
    monkeypatch.setattr(runtime_client.httpx, "get", lambda *a, **k: pytest.fail("规则模式不得发出探测请求"))
    with pytest.raises(RuntimeProbeError):
        runtime_client.probe_configured_model()
