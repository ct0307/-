"""导入状态机和汇总服务测试。"""

import pytest

from app.core.config import Settings
from app.services.imports import service
from app.services.imports.service import ImportConflict, summarize_import, target_status


def test_import_summary_separates_ready_confirmation_and_failures():
    result = summarize_import(["ready", "awaiting_confirmation", "failed", "parsing"])

    assert result.total == 4
    assert result.ready == 1
    assert result.failed == 1
    assert result.status == "processing"


@pytest.mark.parametrize(
    ("suggested_type", "confidence", "expected"),
    [
        ("采购合同", 0.85, "awaiting_confirmation"),
        ("采购合同", 0.84, "awaiting_confirmation"),
        ("", 0.20, "awaiting_confirmation"),
    ],
)
def test_target_status_uses_confidence_threshold(suggested_type, confidence, expected):
    assert target_status(suggested_type, confidence) == expected


def test_auto_ready_is_disabled_by_default_even_for_eligible_high_confidence(monkeypatch):
    assert Settings(_env_file=None).CONTRACT_TYPE_AUTO_READY_ENABLED is False
    monkeypatch.setattr(service, "settings", type("Config", (), {"CONTRACT_TYPE_AUTO_READY_ENABLED": False, "CONTRACT_TYPE_READY_THRESHOLD": 0.85})())
    assert target_status("采购合同", 0.99, auto_ready_eligible=True) == "awaiting_confirmation"


@pytest.mark.parametrize(
    ("suggested_type", "confidence", "eligible", "review", "expected"),
    [
        ("采购合同", 0.99, True, True, "awaiting_confirmation"),
        ("采购合同", 0.99, True, False, "ready"),
        ("采购合同", 0.99, False, False, "awaiting_confirmation"),
        ("", 0.99, True, False, "awaiting_confirmation"),
        ("采购合同", 0.84, True, False, "awaiting_confirmation"),
    ],
)
def test_auto_ready_requires_every_gate(monkeypatch, suggested_type, confidence, eligible, review, expected):
    monkeypatch.setattr(service, "settings", type("Config", (), {"CONTRACT_TYPE_AUTO_READY_ENABLED": True, "CONTRACT_TYPE_READY_THRESHOLD": 0.85})())
    assert target_status(
        suggested_type, confidence, auto_ready_eligible=eligible, requires_review=review,
    ) == expected


def test_only_failed_import_item_can_retry():
    with pytest.raises(ImportConflict):
        target_status("采购合同", 0.9, current_status="ready", retry=True)
