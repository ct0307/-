"""冻结合同语料画像的数据模型与严格加载。"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping


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


@dataclass(frozen=True)
class ContractCase:
    case_id: str
    title: str
    scenario: str
    contract_type: str
    format: str
    render_mode: str
    document_state: str
    primary_roles: tuple[str, ...]
    parties: tuple[str, ...]
    price_model: str
    amount_heading: str
    truth: Mapping[str, Any]
    related_documents: tuple[str, ...]
    risk_tags: tuple[str, ...]
    target_pages: int
    layout_variant: str
    source_profiles: tuple[str, ...]
    distributed_fields: bool
    clause_conflict: bool


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


def _required_text(row: Mapping[str, Any], field: str, index: int) -> str:
    value = row.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"cases[{index}].{field} 必须是非空字符串")
    return value.strip()


def _string_tuple(row: Mapping[str, Any], field: str, index: int) -> tuple[str, ...]:
    value = row.get(field)
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise ValueError(f"cases[{index}].{field} 必须是字符串数组")
    return tuple(item.strip() for item in value)


def _load_case(row: object, index: int) -> ContractCase:
    item = _require_mapping(row, f"cases[{index}]")
    truth = _require_mapping(item.get("truth"), f"cases[{index}].truth")
    required_truth = {"party_a", "party_b", "subject", "amount", "duration", "payment_terms"}
    if set(truth) != required_truth:
        raise ValueError(f"cases[{index}].truth 字段必须为固定六要素")
    if not isinstance(truth["payment_terms"], list) or any(
        not isinstance(term, str) or not term.strip() for term in truth["payment_terms"]
    ):
        raise ValueError(f"cases[{index}].truth.payment_terms 必须是字符串数组")
    for field in required_truth - {"payment_terms"}:
        if truth[field] is not None and not isinstance(truth[field], str):
            raise ValueError(f"cases[{index}].truth.{field} 必须是字符串或 null")

    file_format = _required_text(item, "format", index)
    if file_format not in EXPECTED_FORMATS:
        raise ValueError(f"cases[{index}].format 不受支持")
    render_mode = _required_text(item, "render_mode", index)
    if render_mode not in {"native", "scanned", "mixed"}:
        raise ValueError(f"cases[{index}].render_mode 不受支持")
    target_pages = item.get("target_pages")
    if not isinstance(target_pages, int) or not 4 <= target_pages <= 30:
        raise ValueError(f"cases[{index}].target_pages 必须在 4 至 30 之间")

    return ContractCase(
        case_id=_required_text(item, "case_id", index),
        title=_required_text(item, "title", index),
        scenario=_required_text(item, "scenario", index),
        contract_type=_required_text(item, "contract_type", index),
        format=file_format,
        render_mode=render_mode,
        document_state=_required_text(item, "document_state", index),
        primary_roles=_string_tuple(item, "primary_roles", index),
        parties=_string_tuple(item, "parties", index),
        price_model=_required_text(item, "price_model", index),
        amount_heading=_required_text(item, "amount_heading", index),
        truth=MappingProxyType(dict(truth)),
        related_documents=_string_tuple(item, "related_documents", index),
        risk_tags=_string_tuple(item, "risk_tags", index),
        target_pages=target_pages,
        layout_variant=_required_text(item, "layout_variant", index),
        source_profiles=_string_tuple(item, "source_profiles", index),
        distributed_fields=item.get("distributed_fields") is True,
        clause_conflict=item.get("clause_conflict") is True,
    )


def load_cases(path: Path) -> tuple[ContractCase, ...]:
    """加载全部显式案例，拒绝重复编号和不完整业务事实。"""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("cases.json 必须是数组")
    cases = tuple(_load_case(row, index) for index, row in enumerate(payload))
    case_ids = [case.case_id for case in cases]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("case_id 不得重复")
    return cases
