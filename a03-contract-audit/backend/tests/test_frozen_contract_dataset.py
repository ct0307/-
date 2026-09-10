"""高拟真合成冻结合同集的画像与生成契约。"""
from collections import Counter
import json
from pathlib import Path

import pytest

from evaluation.datasets.frozen_contracts_v1.models import load_cases, load_profile


DATASET_ROOT = (
    Path(__file__).parents[1]
    / "evaluation"
    / "datasets"
    / "frozen_contracts_v1"
)


def _write_json(path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _valid_profile():
    return {
        "version": "1.0.0",
        "valid_count": 50,
        "invalid_count": 2,
        "formats": {
            "docx": 14,
            "text_pdf": 21,
            "scanned_or_mixed_pdf": 15,
        },
        "scenarios": {
            "采购、供货与销售": 12,
            "技术、软件与数据服务": 10,
            "运维、咨询、培训与业务外包": 8,
            "房屋、设备与场地租赁": 6,
            "建设、装修、监理与承揽": 5,
            "人力资源、保险与员工服务": 4,
            "保密、数据处理与知识产权": 3,
            "框架订单、补充协议与多方合作": 2,
        },
        "anti_fit": {
            "non_party_ab_ratio": 0.4,
            "non_contract_amount_heading_ratio": 0.3,
            "nullable_or_formula_amount_ratio": 0.2,
            "distributed_field_ratio": 0.2,
            "clause_conflict_ratio": 0.1,
        },
    }


def test_profile_requires_exact_realistic_distribution(tmp_path):
    profile = _valid_profile()
    profile["formats"] = {
        "docx": 30,
        "text_pdf": 15,
        "scanned_or_mixed_pdf": 5,
    }
    path = _write_json(tmp_path / "corpus-profile.json", profile)

    with pytest.raises(ValueError, match="格式分布"):
        load_profile(path)


def test_cases_match_frozen_real_world_profile():
    profile = load_profile(DATASET_ROOT / "corpus-profile.json")
    cases = load_cases(DATASET_ROOT / "cases.json")

    assert [case.case_id for case in cases] == [f"FC-{index:03d}" for index in range(1, 51)]
    assert dict(Counter(case.format for case in cases)) == dict(profile.formats)
    assert dict(Counter(case.scenario for case in cases)) == dict(profile.scenarios)
    assert sum(case.primary_roles != ("甲方", "乙方") for case in cases) >= 20
    assert sum(case.amount_heading != "合同金额" for case in cases) >= 15
    assert sum(case.truth["amount"] is None for case in cases) >= 10
    assert sum(case.distributed_fields for case in cases) >= 10
    assert sum(case.clause_conflict for case in cases) >= 5
    assert sum(len(case.parties) >= 3 for case in cases) >= 5
    assert sum(bool(case.related_documents) for case in cases) >= 12
    assert sum(case.target_pages > 12 for case in cases) >= 10
    assert all(4 <= case.target_pages <= 30 for case in cases)


def test_cases_retain_common_enterprise_drafting_conventions():
    cases = load_cases(DATASET_ROOT / "cases.json")

    standard_party_labels = sum(
        case.primary_roles == ("甲方", "乙方") for case in cases
    )
    standard_amount_headings = sum(
        case.amount_heading == "合同金额" for case in cases
    )

    # 真实企业合同既包含角色化称谓，也大量保留通用的甲乙方和合同金额写法。
    assert 15 <= standard_party_labels <= 25
    assert 8 <= standard_amount_headings <= 20
