"""审查规则的严格数据契约。"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


RuleCategory = Literal[
    "completeness",
    "format",
    "numeric",
    "temporal",
    "cross_clause",
    "applicability",
    "escalation",
]


class RuleDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    rule_id: str = Field(pattern=r"^[A-Z][A-Z0-9-]{5,63}$")
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    name: str = Field(min_length=2, max_length=80)
    category: RuleCategory
    agent: Literal["legal", "finance", "system"]
    dimensions: tuple[str, ...] = Field(min_length=1)
    contract_types: tuple[str, ...] = ()
    severity: Literal["high", "medium", "low"]
    handler: str = Field(min_length=2, max_length=64)
    manual_review_on_unclear: bool = True

    @field_validator("dimensions", "contract_types")
    @classmethod
    def reject_blank_or_duplicate_values(
        cls,
        values: tuple[str, ...],
    ) -> tuple[str, ...]:
        normalized = tuple(value.strip() for value in values)
        if any(not value for value in normalized):
            raise ValueError("规则范围不能包含空值")
        if len(set(normalized)) != len(normalized):
            raise ValueError("规则范围不能包含重复值")
        return normalized
