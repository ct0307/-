"""导入状态机和汇总服务测试。"""

import pytest

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
        ("采购合同", 0.85, "ready"),
        ("采购合同", 0.84, "awaiting_confirmation"),
        ("", 0.20, "awaiting_confirmation"),
    ],
)
def test_target_status_uses_confidence_threshold(suggested_type, confidence, expected):
    assert target_status(suggested_type, confidence) == expected


def test_only_failed_import_item_can_retry():
    with pytest.raises(ImportConflict):
        target_status("采购合同", 0.9, current_status="ready", retry=True)
