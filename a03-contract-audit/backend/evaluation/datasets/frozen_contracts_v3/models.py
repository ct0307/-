"""v3 冻结合同集的不可变数据模型。"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping


EXPECTED_FORMATS = {"docx": 14, "text_pdf": 21, "scanned_or_mixed_pdf": 15}
EXPECTED_DRAFTING_STYLES = {
    "buyer_standard": 6,
    "supplier_standard": 5,
    "business_draft": 5,
    "legal_redline": 4,
    "model_contract": 5,
    "online_terms": 3,
    "framework_order": 4,
    "master_supplement": 4,
    "project_conditions": 4,
    "industry_template": 3,
    "customer_template": 4,
    "short_order": 3,
}
EXPECTED_RISK_LEVELS = {"actionable": 28, "negotiated": 14, "baseline": 8}


@dataclass(frozen=True)
class CorpusProfile:
    version: str
    valid_count: int
    invalid_count: int
    formats: Mapping[str, int]
    drafting_styles: Mapping[str, int]
    risk_levels: Mapping[str, int]


@dataclass(frozen=True)
class PartySpec:
    role: str
    name: str
    address: str = ""
    contact: str = ""


@dataclass(frozen=True)
class TruthSpec:
    subject: str = ""
    pricing: str = ""
    amount: str | None = None
    duration: str = ""
    payment_terms: tuple[str, ...] = ()
    delivery: str = ""
    acceptance: str = ""
    termination: str = ""

    def evaluation_projection(self, parties: tuple[PartySpec, ...]) -> Mapping[str, Any]:
        return MappingProxyType({
            "party_a": parties[0].name if parties else None,
            "party_b": parties[1].name if len(parties) > 1 else None,
            "subject": self.subject or None,
            "amount": self.amount,
            "duration": self.duration or None,
            "payment_terms": list(self.payment_terms),
        })


@dataclass(frozen=True)
class AnnexSpec:
    annex_type: str
    name: str
    version: str
    columns: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]
    precedence: str = ""


@dataclass(frozen=True)
class RiskClause:
    clause_id: str
    text: str
    risk_type: str
    severity: str
    review_reason: str


@dataclass(frozen=True)
class ConflictPair:
    source_a: str
    text_a: str
    source_b: str
    text_b: str
    precedence_rule: str
    effective_value: str


@dataclass(frozen=True)
class RevisionSet:
    deleted_text: str
    inserted_text: str
    comment: str
    author: str
    date: str


@dataclass(frozen=True)
class ContractCase:
    case_id: str
    title: str = ""
    scenario: str = ""
    contract_type: str = ""
    format: str = "text_pdf"
    render_mode: str = "native"
    document_state: str = "signed"
    drafting_style: str = "business_draft"
    risk_level: str = "baseline"
    length_class: str = "standard"
    parties: tuple[PartySpec, ...] = ()
    truth: TruthSpec = field(default_factory=TruthSpec)
    annex_types: tuple[str, ...] = ()
    risk_clauses: tuple[RiskClause, ...] = ()
    conflicts: tuple[ConflictPair, ...] = ()
    revision_set: RevisionSet | None = None


def _integer_mapping(payload: object, field_name: str) -> dict[str, int]:
    if not isinstance(payload, dict) or any(
        not isinstance(key, str) or not isinstance(value, int)
        for key, value in payload.items()
    ):
        raise ValueError(f"{field_name} 必须是字符串到整数的对象")
    return payload


def load_profile(path: Path) -> CorpusProfile:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("画像必须是对象")
    formats = _integer_mapping(payload.get("formats"), "formats")
    styles = _integer_mapping(payload.get("drafting_styles"), "drafting_styles")
    risk_levels = _integer_mapping(payload.get("risk_levels"), "risk_levels")
    if payload.get("version") != "3.0.0":
        raise ValueError("画像 version 必须为 3.0.0")
    if payload.get("valid_count") != 50 or payload.get("invalid_count") != 2:
        raise ValueError("数据集数量必须为 50+2")
    if formats != EXPECTED_FORMATS:
        raise ValueError("格式分布不符合 v3 设计")
    if styles != EXPECTED_DRAFTING_STYLES:
        raise ValueError("起草风格分布不符合 v3 设计")
    if risk_levels != EXPECTED_RISK_LEVELS:
        raise ValueError("风险层级分布不符合 v3 设计")
    return CorpusProfile(
        version="3.0.0",
        valid_count=50,
        invalid_count=2,
        formats=MappingProxyType(dict(formats)),
        drafting_styles=MappingProxyType(dict(styles)),
        risk_levels=MappingProxyType(dict(risk_levels)),
    )
