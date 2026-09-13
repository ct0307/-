"""防御性读取审查任务的历史质量快照。"""
from __future__ import annotations

from dataclasses import dataclass
import json
import math
from typing import Mapping


TERMINAL_ITEM_STATUSES = frozenset({"done", "review_required", "failed"})


@dataclass(frozen=True)
class AuditQualitySnapshot:
    requires_review: bool
    ocr_confidence: float | None
    review_reason: str | None
    result: dict[str, object]


def parse_result_snapshot(raw: object) -> dict[str, object]:
    if not isinstance(raw, str):
        return {}
    try:
        candidate = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    return candidate if isinstance(candidate, dict) else {}


def quality_snapshot(item: object, contract: object) -> AuditQualitySnapshot:
    """终态只信任务快照；活动态允许回退到合同当前解析质量。"""
    status = str(getattr(item, "status", ""))
    result = parse_result_snapshot(getattr(item, "result_json", "{}"))
    terminal = status in TERMINAL_ITEM_STATUSES

    if terminal:
        requires_review = status == "review_required"
        raw_ocr = result.get("ocr_confidence")
        raw_reason = result.get("review_reason")
    else:
        snapshot_review = result.get("requires_review")
        requires_review = (
            snapshot_review
            if type(snapshot_review) is bool
            else bool(getattr(contract, "requires_review", False))
        )
        raw_ocr = result.get("ocr_confidence", getattr(contract, "ocr_confidence", None))
        raw_reason = result.get("review_reason", getattr(contract, "review_reason", None))

    review_reason = raw_reason if requires_review and isinstance(raw_reason, str) else None
    return AuditQualitySnapshot(
        requires_review=requires_review,
        ocr_confidence=safe_ocr_confidence(raw_ocr),
        review_reason=review_reason,
        result=result,
    )


def safe_ocr_confidence(value: object) -> float | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    try:
        normalized = float(value)
    except (OverflowError, ValueError):
        return None
    if not math.isfinite(normalized) or not 0 <= normalized <= 1:
        return None
    return normalized


def safe_coverage(value: object) -> dict[str, int] | None:
    if not isinstance(value, Mapping):
        return None
    planned = value.get("planned")
    completed = value.get("completed")
    if (
        type(planned) is not int
        or type(completed) is not int
        or planned < 0
        or completed < 0
        or completed > planned
    ):
        return None
    return {"planned": planned, "completed": completed}
