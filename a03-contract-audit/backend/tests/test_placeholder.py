"""应用存活接口契约。"""
from app.main import health


def test_health_returns_application_status():
    result = health()

    assert result["status"] == "ok"
    assert result["app"]
