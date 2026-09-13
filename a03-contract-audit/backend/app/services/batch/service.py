"""批次状态机、进度聚合与失败重试规则。"""
from dataclasses import dataclass

BATCH_STATUSES = frozenset({
    "queued", "running", "done", "review_required", "partial_failed", "failed",
})
ITEM_STATUSES = frozenset({
    "queued", "parsing", "reviewing", "validating", "done", "review_required", "failed",
})
ACTIVE_AUDIT_ITEM_STATUSES = frozenset({
    "queued", "parsing", "reviewing", "validating", "auditing",
})
TERMINAL_ITEM_STATUSES = frozenset({"done", "review_required", "failed"})

ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "queued": frozenset({"parsing", "failed"}),
    "parsing": frozenset({"reviewing", "failed"}),
    "reviewing": frozenset({"validating", "failed"}),
    "validating": frozenset({"done", "review_required", "failed"}),
    "failed": frozenset({"queued"}),
    "done": frozenset(),
    "review_required": frozenset(),
}


class InvalidBatchTransition(ValueError):
    """批次项状态发生非法跃迁。"""


@dataclass(frozen=True)
class BatchProgress:
    total: int
    completed: int
    failed: int
    status: str


@dataclass(frozen=True)
class RetryDecision:
    status: str
    attempts: int


def summarize(statuses: list[str]) -> BatchProgress:
    """从批次项状态计算持久化进度，终态数量包含成功和失败。"""
    unknown = set(statuses) - ITEM_STATUSES
    if unknown:
        raise ValueError(f"未知批次项状态: {sorted(unknown)}")

    total = len(statuses)
    completed = sum(status in TERMINAL_ITEM_STATUSES for status in statuses)
    failed = statuses.count("failed")
    if total == 0 or all(status == "queued" for status in statuses):
        status = "queued"
    elif completed < total:
        status = "running"
    elif failed == 0 and "review_required" in statuses:
        status = "review_required"
    elif failed == 0:
        status = "done"
    elif failed == total:
        status = "failed"
    else:
        status = "partial_failed"
    return BatchProgress(total=total, completed=completed, failed=failed, status=status)


def transition_item(current: str, target: str) -> str:
    """校验批次项状态流转，成功时返回目标状态。"""
    if current not in ITEM_STATUSES or target not in ITEM_STATUSES:
        raise InvalidBatchTransition(f"未知状态流转: {current} -> {target}")
    if target not in ALLOWED_TRANSITIONS[current]:
        raise InvalidBatchTransition(f"非法状态流转: {current} -> {target}")
    return target


def retry_failed_item(status: str, *, attempts: int) -> RetryDecision:
    """失败项只增加一次重试计数；已排队的重复请求保持幂等。"""
    if status == "queued":
        return RetryDecision(status="queued", attempts=attempts)
    if status != "failed":
        raise InvalidBatchTransition(f"仅失败项可重试，当前状态: {status}")
    return RetryDecision(status=transition_item(status, "queued"), attempts=attempts + 1)
