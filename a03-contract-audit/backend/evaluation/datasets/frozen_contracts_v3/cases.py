"""v3 案例入口；逐案业务事实将在下一阶段写入。"""
from __future__ import annotations

from .models import ContractCase


CASES = tuple(ContractCase(case_id=f"F3-{index:03d}") for index in range(1, 51))


def load_cases() -> tuple[ContractCase, ...]:
    return CASES
