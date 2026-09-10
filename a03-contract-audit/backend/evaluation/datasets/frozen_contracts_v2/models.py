"""v2 冻结语料画像和案例事实模型。"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from types import MappingProxyType
from typing import Mapping


EXPECTED_FORMATS = {
    "docx": 14,
    "text_pdf": 21,
    "scanned_or_mixed_pdf": 15,
}
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
EXPECTED_RISK_LEVELS = {
    "actionable": 28,
    "negotiated": 14,
    "baseline": 8,
}


@dataclass(frozen=True)
class CorpusProfile:
    version: str
    valid_count: int
    invalid_count: int
    formats: Mapping[str, int]
    drafting_styles: Mapping[str, int]
    risk_levels: Mapping[str, int]


def _mapping(payload: object, field: str) -> dict[str, int]:
    if not isinstance(payload, dict) or any(
        not isinstance(key, str) or not isinstance(value, int)
        for key, value in payload.items()
    ):
        raise ValueError(f"{field} 必须是字符串到整数的对象")
    return payload


def load_profile(path: Path) -> CorpusProfile:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("画像必须是对象")
    if payload.get("version") != "2.0.0":
        raise ValueError("画像 version 必须为 2.0.0")
    if payload.get("valid_count") != 50 or payload.get("invalid_count") != 2:
        raise ValueError("数据集数量必须为 50+2")

    formats = _mapping(payload.get("formats"), "formats")
    styles = _mapping(payload.get("drafting_styles"), "drafting_styles")
    risk_levels = _mapping(payload.get("risk_levels"), "risk_levels")
    if formats != EXPECTED_FORMATS:
        raise ValueError("格式分布不符合 v2 冻结设计")
    if styles != EXPECTED_DRAFTING_STYLES:
        raise ValueError("起草风格分布不符合 v2 冻结设计")
    if risk_levels != EXPECTED_RISK_LEVELS:
        raise ValueError("风险等级分布不符合 v2 冻结设计")

    return CorpusProfile(
        version="2.0.0",
        valid_count=50,
        invalid_count=2,
        formats=MappingProxyType(dict(formats)),
        drafting_styles=MappingProxyType(dict(styles)),
        risk_levels=MappingProxyType(dict(risk_levels)),
    )
