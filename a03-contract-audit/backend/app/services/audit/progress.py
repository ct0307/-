"""审查进度的纯领域规则。"""
from typing import Literal


ProgressStage = Literal[
    "queued",
    "claimed",
    "parsing",
    "reviewing",
    "verifying",
    "persisting",
    "completed",
    "failed",
]


def normalize_progress(value: int, *, terminal_success: bool = False) -> int:
    """限制进度范围；成功终态发布前不得提前返回 100%。"""
    upper_bound = 100 if terminal_success else 99
    return max(0, min(upper_bound, int(value)))
