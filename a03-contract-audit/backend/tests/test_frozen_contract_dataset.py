"""高拟真合成冻结合同集的画像与生成契约。"""
import json

import pytest

from evaluation.datasets.frozen_contracts_v1.models import load_profile


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
