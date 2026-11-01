"""合同审查候选 Claim 的内部数据契约。"""
from __future__ import annotations

import hashlib
import re
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.services.audit.protocol import RiskFinding


CLAIM_SCHEMA_VERSION = "claim-v1"


class AuditClaim(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    schema_version: Literal["claim-v1"] = CLAIM_SCHEMA_VERSION
    claim_id: str = ""
    agent: Literal["legal", "finance", "system"]
    level: Literal["high", "medium", "low"]
    category: str = Field(min_length=2, max_length=64)
    dimension: str = Field(min_length=2, max_length=32)
    subject: str = Field(default="", max_length=128)
    action: str = Field(default="", max_length=256)
    condition: str = Field(default="", max_length=256)
    consequence: str = Field(default="", max_length=256)
    quote: str = Field(min_length=2, max_length=500)
    source_window_id: str | None = Field(default=None, max_length=64)
    clause_ids: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    review_targets: list[Literal["legal", "finance"]] = Field(
        default_factory=list
    )

    @model_validator(mode="after")
    def assign_claim_id(self) -> Self:
        expected = claim_id_for(self)
        if self.claim_id and self.claim_id != expected:
            raise ValueError("claim_id 与 Claim 内容不一致")
        self.claim_id = expected
        return self


def claim_id_for(claim: AuditClaim) -> str:
    """沿用既有风险 ID 算法，避免 Schema 升级改变历史引用。"""
    payload = re.sub(
        r"\s+",
        "",
        f"{claim.agent}\0{claim.category}\0{claim.quote}",
    )
    return "C-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16].upper()


def normalize_finding(
    finding: RiskFinding,
    *,
    agent: Literal["legal", "finance", "system"],
    dimension: str,
    window_id: str,
    clause_ids: tuple[str, ...] | list[str],
) -> AuditClaim:
    """将模型候选直接映射为 Claim，不补写模型未提供的事实。"""
    return AuditClaim(
        agent=agent,
        level=finding.level,
        category=finding.category,
        dimension=dimension,
        quote=finding.quote,
        source_window_id=window_id,
        clause_ids=list(clause_ids),
    )
