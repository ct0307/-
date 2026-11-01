import json
from types import SimpleNamespace

import pytest

from app.schemas.batch import BatchItemOut
from app.services.audit.failure import audit_failure


def _item(*, code=None, snapshot=None, error=None):
    return SimpleNamespace(
        id=1, contract_id=1, filename="合同.pdf", status="failed", attempts=0,
        error_code=code, error=error, started_at=None, finished_at=None,
        result_json=json.dumps(snapshot or {}, ensure_ascii=False),
        contract=SimpleNamespace(review_reason="另一代合同原因", requires_review=True),
    )


@pytest.mark.parametrize("code,retryable", [
    ("MODEL_TIMEOUT", True), ("MODEL_UNAVAILABLE", True),
    ("OUTPUT_TRUNCATED", True), ("INVALID_MODEL_OUTPUT", True),
    ("AUDIT_PERSISTENCE_UNAVAILABLE", True), ("MODEL_REJECTED", False),
    ("FACT_VALIDATION_FAILED", False), ("CONTRACT_TEXT_INCOMPLETE", False),
    ("UNKNOWN_SECRET", False),
])
def test_failure_maps_known_codes_without_exposing_raw_error(code, retryable):
    info = audit_failure(_item(code=code, error="C:/secret 合同正文 token=private"))
    assert info.retryable is retryable
    assert info.message and info.action
    assert "private" not in repr(info)
    assert "secret" not in repr(info)


def test_batch_schema_recovers_historical_timeout_from_own_snapshot():
    item = _item(snapshot={
        "quality_reasons": ["INCOMPLETE_COVERAGE", "MODEL_TIMEOUT"],
        "issues": [{"code": "MODEL_TIMEOUT", "detail": "供应商敏感原文"}],
        "review_reason": "审查覆盖不完整；模型调用超时",
    })
    payload = BatchItemOut.model_validate(item)
    assert payload.error_code == "MODEL_TIMEOUT"
    assert payload.retryable is True
    assert "超时" in payload.error
    assert payload.error_action
    assert "敏感原文" not in repr(payload.model_dump())
    assert "另一代" not in repr(payload.model_dump())


def test_legacy_reason_is_matched_to_safe_known_message():
    payload = BatchItemOut.model_validate(_item(snapshot={
        "review_reason": "审查覆盖不完整；模型输出被截断；token=private",
    }))
    assert payload.error_code == "OUTPUT_TRUNCATED"
    assert "截断" in payload.error
    assert "private" not in repr(payload.model_dump())


def test_unknown_and_corrupt_snapshot_have_safe_non_retryable_fallback():
    item = _item()
    item.result_json = "not-json"
    payload = BatchItemOut.model_validate(item)
    assert payload.error_code == "AUDIT_INTERNAL_ERROR"
    assert payload.retryable is False
    assert "管理员" in payload.error_action


def test_success_has_no_failure_metadata():
    item = _item(code="MODEL_TIMEOUT")
    item.status = "done"
    info = audit_failure(item)
    assert info is None
