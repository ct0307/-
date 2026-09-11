"""真实模型运行端点健康状态契约。"""
from app.services.runtime.status import RuntimeProbeError, probe_runtime, sanitize_endpoint


def test_runtime_is_offline_when_health_request_fails():
    def failed_probe():
        raise OSError("connection refused")

    result = probe_runtime(failed_probe)

    assert result.status == "offline"
    assert result.checked_at is not None


def test_runtime_preserves_classified_probe_failure():
    def failed_probe():
        raise RuntimeProbeError("timeout", "模型端点请求超时", retryable=True)

    result = probe_runtime(
        failed_probe,
        provider="deepseek",
        endpoint="https://api.deepseek.com/v1?api_key=secret",
    )

    assert result.status == "offline"
    assert result.error_code == "timeout"
    assert result.detail == "模型端点请求超时"
    assert result.endpoint == "https://api.deepseek.com"


def test_runtime_maps_unclassified_failure_without_exposing_exception():
    result = probe_runtime(lambda: (_ for _ in ()).throw(RuntimeError("secret-token")))

    assert result.status == "offline"
    assert result.error_code == "probe_failed"
    assert result.detail == "模型端点探测失败"
    assert "secret-token" not in (result.detail or "")


def test_runtime_is_online_only_after_successful_probe():
    result = probe_runtime(
        lambda: {"model": "qwen2.5:14b"},
        provider="qwen",
        endpoint="http://user:secret@localhost:11434/v1?token=secret",
    )

    assert result.status == "online"
    assert result.model == "qwen2.5:14b"
    assert result.provider == "qwen"
    assert result.endpoint == "http://localhost:11434"


def test_runtime_is_unknown_when_probe_response_has_no_model():
    result = probe_runtime(lambda: {"status": "ok"})

    assert result.status == "unknown"
    assert result.detail == "健康探测响应缺少模型标识"


def test_endpoint_label_removes_credentials_query_and_fragment():
    assert (
        sanitize_endpoint("https://user:pass@example.com:8443/v1?api_key=secret#token")
        == "https://example.com:8443"
    )


def test_endpoint_label_does_not_expose_secret_path_segments():
    assert sanitize_endpoint("https://api.example.com/tenant/secret-token/v1") == "https://api.example.com"


def test_endpoint_label_formats_ipv6_authority_without_path():
    assert sanitize_endpoint("http://[::1]:11434/private/token") == "http://[::1]:11434"
