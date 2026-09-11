import threading
import time

from app.api.v1.endpoints import runtime
from app.api.v1.endpoints.runtime import PublicRuntimeStatus


def test_expired_runtime_cache_does_not_hold_lock_during_probe(monkeypatch):
    started = threading.Event()
    release = threading.Event()
    calls = 0

    def slow_probe():
        nonlocal calls
        calls += 1
        started.set()
        release.wait(timeout=2)
        return {"model": "deepseek-v4-pro"}

    monkeypatch.setattr(runtime, "probe_configured_model", slow_probe)
    monkeypatch.setattr(runtime.settings, "LLM_PROVIDER", "deepseek")
    monkeypatch.setattr(runtime.settings, "LLM_BASE_URL", "https://api.deepseek.com/v1")
    runtime._runtime_status_cache.clear()
    runtime._runtime_status_cache.update({"expires_at": 0.0, "value": None})

    first_result: list[PublicRuntimeStatus] = []
    first = threading.Thread(target=lambda: first_result.append(runtime._get_cached_runtime_status(now=10)))
    first.start()
    assert started.wait(timeout=1)

    second = runtime._get_cached_runtime_status(now=10)

    assert second.status == "checking"
    assert calls == 1
    release.set()
    first.join(timeout=2)
    assert first_result[0].status == "online"


def test_runtime_snapshot_marks_expired_success_as_degraded(monkeypatch):
    cached = PublicRuntimeStatus(
        status="online",
        checked_at="2026-09-11T10:00:00Z",
        provider="deepseek",
        model="deepseek-v4-pro",
    )
    runtime._runtime_status_cache.clear()
    runtime._runtime_status_cache.update({"expires_at": 1.0, "value": cached})
    monkeypatch.setattr(runtime, "monotonic", lambda: 2.0)

    snapshot = runtime._get_runtime_status_snapshot()

    assert snapshot.status == "degraded"
    assert snapshot.model == "deepseek-v4-pro"
    assert snapshot.error_code == "status_stale"
