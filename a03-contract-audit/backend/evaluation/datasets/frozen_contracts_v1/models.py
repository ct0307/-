"""冻结合同语料画像的数据模型与严格加载。"""
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
EXPECTED_SCENARIOS = {
    "采购、供货与销售": 12,
    "技术、软件与数据服务": 10,
    "运维、咨询、培训与业务外包": 8,
    "房屋、设备与场地租赁": 6,
    "建设、装修、监理与承揽": 5,
    "人力资源、保险与员工服务": 4,
    "保密、数据处理与知识产权": 3,
    "框架订单、补充协议与多方合作": 2,
}
EXPECTED_ANTI_FIT = {
    "non_party_ab_ratio": 0.4,
    "non_contract_amount_heading_ratio": 0.3,
    "nullable_or_formula_amount_ratio": 0.2,
    "distributed_field_ratio": 0.2,
    "clause_conflict_ratio": 0.1,
}


@dataclass(frozen=True)
class CorpusProfile:
    version: str
    valid_count: int
    invalid_count: int
    formats: Mapping[str, int]
    scenarios: Mapping[str, int]
    anti_fit: Mapping[str, float]


def _require_mapping(payload: object, field: str) -> dict:
    if not isinstance(payload, dict):
        raise ValueError(f"{field} 必须是对象")
    return payload


def load_profile(path: Path) -> CorpusProfile:
    """加载固定 v1 画像，拒绝任何会弱化现实性的分布漂移。"""
    payload = _require_mapping(json.loads(path.read_text(encoding="utf-8")), "画像")
    if payload.get("version") != "1.0.0":
        raise ValueError("画像 version 必须为 1.0.0")
    if payload.get("valid_count") != 50 or payload.get("invalid_count") != 2:
        raise ValueError("数据集数量必须为 50+2")

    formats = _require_mapping(payload.get("formats"), "formats")
    if formats != EXPECTED_FORMATS:
        raise ValueError("格式分布不符合冻结设计")
    scenarios = _require_mapping(payload.get("scenarios"), "scenarios")
    if scenarios != EXPECTED_SCENARIOS:
        raise ValueError("业务场景分布不符合冻结设计")
    anti_fit = _require_mapping(payload.get("anti_fit"), "anti_fit")
    if anti_fit != EXPECTED_ANTI_FIT:
        raise ValueError("防迎合比例不符合冻结设计")

    return CorpusProfile(
        version="1.0.0",
        valid_count=50,
        invalid_count=2,
        formats=MappingProxyType(dict(formats)),
        scenarios=MappingProxyType(dict(scenarios)),
        anti_fit=MappingProxyType(dict(anti_fit)),
    )
