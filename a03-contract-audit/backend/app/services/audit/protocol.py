from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


AUDIT_PROTOCOL_VERSION = "candidate-v4"
AUDIT_JSON_FORMAT = {"type": "json_object"}


def _strip_string(value: object) -> object:
    return value.strip() if isinstance(value, str) else value


class RiskCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, strict=True)

    level: Literal["high", "medium", "low"]
    category: str = Field(min_length=2, max_length=64)
    quote: str = Field(min_length=2, max_length=500)
    reason: str = Field(min_length=4, max_length=800)
    suggestion: str = Field(min_length=4, max_length=800)

    _strip_level = field_validator("level", mode="before")(_strip_string)


class ReviewedRiskCandidate(RiskCandidate):
    """系统附加真实调用来源；此类型不用于模型输出解析。"""

    source_window_id: str = Field(min_length=1, max_length=64)
    source_clause_ids: list[str] = Field(default_factory=list)


class RiskEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, strict=True)

    risks: list[RiskCandidate] = Field(max_length=5)
    has_more: bool


def parse_risk_envelope(text: str) -> RiskEnvelope:
    stripped = text.strip()
    if not stripped.startswith("{") or not stripped.endswith("}"):
        raise ValueError("风险输出必须是 JSON 对象")
    return RiskEnvelope.model_validate_json(stripped)


class RiskFinding(BaseModel):
    """候选发现阶段的紧凑输出，不承载长篇分析。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, strict=True)

    level: Literal["high", "medium", "low"]
    category: str = Field(min_length=2, max_length=64)
    quote: str = Field(min_length=2, max_length=320)

    _strip_level = field_validator("level", mode="before")(_strip_string)


class RiskFindingEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, strict=True)

    risks: list[RiskFinding] = Field(max_length=5)
    has_more: bool


class RiskEnrichment(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, strict=True)

    reason: str = Field(min_length=4, max_length=400)
    suggestion: str = Field(min_length=4, max_length=400)


class RiskEnrichmentItem(RiskEnrichment):
    candidate_id: str = Field(min_length=8, max_length=64)


class RiskEnrichmentBatch(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, strict=True)

    items: list[RiskEnrichmentItem] = Field(min_length=1, max_length=5)

    @model_validator(mode="after")
    def reject_duplicate_candidate_ids(self) -> Self:
        candidate_ids = [item.candidate_id for item in self.items]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("批量补全 candidate_id 不能重复")
        return self


def parse_risk_finding_envelope(text: str) -> RiskFindingEnvelope:
    stripped = text.strip()
    if not stripped.startswith("{") or not stripped.endswith("}"):
        raise ValueError("候选输出必须是 JSON 对象")
    return RiskFindingEnvelope.model_validate_json(stripped)


def parse_risk_enrichment(text: str) -> RiskEnrichment:
    stripped = text.strip()
    if not stripped.startswith("{") or not stripped.endswith("}"):
        raise ValueError("风险补全输出必须是 JSON 对象")
    return RiskEnrichment.model_validate_json(stripped)


def parse_risk_enrichment_batch(text: str) -> RiskEnrichmentBatch:
    stripped = text.strip()
    if not stripped.startswith("{") or not stripped.endswith("}"):
        raise ValueError("批量风险补全输出必须是 JSON 对象")
    return RiskEnrichmentBatch.model_validate_json(stripped)


ReviewIssueCode = Literal[
    "OUTPUT_TRUNCATED",
    "INVALID_MODEL_OUTPUT",
    "MODEL_TIMEOUT",
    "MODEL_UNAVAILABLE",
    "MODEL_REJECTED",
    "PAGINATION_EXHAUSTED",
    "EVIDENCE_UNRESOLVED",
    "ORIGINAL_TEXT_UNRESOLVED",
    "PARSE_QUALITY_LOW",
    "CONTRACT_TEXT_INCOMPLETE",
    "SECONDARY_REVIEW_CONFLICT",
    "UNBOUND_CONFLICT",
    "AUDIT_DEADLINE_EXCEEDED",
    "DIMENSION_MISMATCH",
    "FACT_VALIDATION_FAILED",
]


class ReviewIssue(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, strict=True)

    code: ReviewIssueCode
    agent: str = Field(min_length=1, max_length=16)
    window_id: str | None = Field(default=None, max_length=64)
    detail: str = Field(min_length=1, max_length=255)

    _strip_code = field_validator("code", mode="before")(_strip_string)


class AgentReviewResult(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, strict=True)

    candidates: list[ReviewedRiskCandidate] = Field(default_factory=list)
    issues: list[ReviewIssue] = Field(default_factory=list)
    complete: bool
    planned_windows: int = Field(default=1, ge=1)
    completed_windows: int = Field(default=0, ge=0)

    @model_validator(mode="before")
    @classmethod
    def default_completed_windows_for_complete_result(cls, value: Any) -> Any:
        if (
            not isinstance(value, dict)
            or value.get("complete") is not True
            or "completed_windows" in value
        ):
            return value
        normalized = value.copy()
        normalized["completed_windows"] = normalized.get("planned_windows", 1)
        return normalized

    @model_validator(mode="after")
    def validate_window_progress(self) -> Self:
        if self.completed_windows > self.planned_windows:
            raise ValueError("completed_windows 不能大于 planned_windows")
        if self.complete and self.completed_windows != self.planned_windows:
            raise ValueError("complete=True 时必须完成所有窗口")
        return self


class SecondaryDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, strict=True)

    claim_id: str = Field(min_length=8, max_length=64)
    verdict: Literal["confirm", "reject", "conflict"]
    reason_code: Literal[
        "EVIDENCE_SUPPORTS_CANDIDATE",
        "EVIDENCE_DOES_NOT_SUPPORT_CANDIDATE",
        "EVIDENCE_CONFLICT",
    ]
    evidence_ids: list[str] = Field(default_factory=list, max_length=8)

    _strip_verdict = field_validator("verdict", mode="before")(_strip_string)
    _strip_reason_code = field_validator("reason_code", mode="before")(_strip_string)

    @model_validator(mode="after")
    def validate_reason_matches_verdict(self) -> Self:
        expected = {
            "confirm": "EVIDENCE_SUPPORTS_CANDIDATE",
            "reject": "EVIDENCE_DOES_NOT_SUPPORT_CANDIDATE",
            "conflict": "EVIDENCE_CONFLICT",
        }[self.verdict]
        if self.reason_code != expected:
            raise ValueError("reason_code 与 verdict 不一致")
        return self


class SecondaryEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, strict=True)

    decisions: list[SecondaryDecision] = Field(default_factory=list, max_length=5)


def parse_secondary_envelope(text: str) -> SecondaryEnvelope:
    stripped = text.strip()
    if not stripped.startswith("{") or not stripped.endswith("}"):
        raise ValueError("二次复核输出必须是 JSON 对象")
    return SecondaryEnvelope.model_validate_json(stripped)
