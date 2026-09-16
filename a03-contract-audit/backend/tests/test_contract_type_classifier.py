"""合同类型分类器的确定性行为。"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.session import Base
from app.models.models import ContractTypeProfile, LookupItem
from app.services.imports import service as import_service
from app.services.imports.classifier import classify_contract_type as _classify_contract_type
from app.services.imports.service import target_status
from app.services.imports.type_profiles import TypeProfile, load_type_profiles


TYPES = ["采购合同", "软件开发外包合同", "劳动合同", "租赁合同", "保密协议"]
ALL_TYPES = [
    "软件开发外包合同", "技术服务合同", "采购合同", "销售合同", "劳动合同",
    "租赁合同", "保密协议", "合作协议", "服务协议", "框架协议",
    "技术开发合同", "合作合同", "服务合同", "劳务合同",
]

DEFAULT_PROFILES = {
    "软件开发外包合同": TypeProfile(
        aliases=("软件开发", "软件外包", "系统开发"),
        positive_signals=("软件开发", "系统开发", "源代码", "软件外包"),
    ),
    "技术服务合同": TypeProfile(
        aliases=("技术服务", "技术支持", "技术维护"),
        positive_signals=("技术服务", "技术支持", "技术维护"),
    ),
    "采购合同": TypeProfile(
        aliases=("采购", "购置"),
        positive_signals=("采购", "购置", "供货", "设备"),
    ),
    "销售合同": TypeProfile(
        aliases=("销售", "出售"),
        positive_signals=("销售", "出售", "售卖"),
    ),
    "劳动合同": TypeProfile(
        aliases=("劳动",),
        positive_signals=("劳动关系", "试用期", "工资"),
    ),
    "租赁合同": TypeProfile(
        aliases=("租赁", "承租", "出租"),
        positive_signals=("租赁", "承租", "出租"),
    ),
    "保密协议": TypeProfile(
        aliases=("保密协议", "保密", "商业秘密"),
        positive_signals=("专项保密协议",),
    ),
    "合作协议": TypeProfile(
        aliases=("合作协议",),
        positive_signals=("合作项目",),
    ),
    "服务协议": TypeProfile(
        aliases=("服务协议",),
        positive_signals=("提供服务",),
    ),
    "框架协议": TypeProfile(
        aliases=("框架",),
        positive_signals=("框架合作", "框架采购"),
    ),
    "技术开发合同": TypeProfile(
        aliases=("技术开发", "研发"),
        positive_signals=("技术开发", "研发", "技术成果", "软件开发", "系统开发", "源代码"),
    ),
    "合作合同": TypeProfile(
        aliases=("合作合同",),
        positive_signals=("合作项目",),
    ),
    "服务合同": TypeProfile(
        aliases=("服务合同",),
        positive_signals=("提供服务",),
    ),
    "劳务合同": TypeProfile(
        aliases=("劳务",),
        positive_signals=("劳务", "劳务报酬", "劳务人员"),
    ),
}


def classify_contract_type(*, profiles=None, **kwargs):
    return _classify_contract_type(
        **kwargs,
        profiles=DEFAULT_PROFILES if profiles is None else profiles,
    )


def test_new_type_is_reachable_from_database_profile():
    profiles = {
        "居间合同": TypeProfile(
            aliases=("居间协议",),
            positive_signals=("居间服务", "委托方"),
        )
    }

    result = classify_contract_type(
        filename="文件.docx",
        text="受托方提供居间服务",
        available_types=["居间合同"],
        profiles=profiles,
    )

    assert result.suggested_type == "居间合同"


def test_type_without_profile_does_not_gain_semantic_candidate():
    result = classify_contract_type(
        filename="文件.docx",
        text="普通描述",
        available_types=["新类型"],
        profiles={},
    )

    assert result.suggested_type == ""


def test_load_type_profiles_only_returns_enabled_available_contract_types():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        enabled = LookupItem(category="contract_type", value="采购合同", sort_order=0)
        enabled.contract_type_profile = ContractTypeProfile(
            aliases_json='[" 采购 ", "采购", ""]',
            positive_signals_json='["供货"]',
            negative_signals_json="[]",
        )
        disabled = LookupItem(category="contract_type", value="销售合同", sort_order=1)
        disabled.contract_type_profile = ContractTypeProfile(
            positive_signals_json='["销售"]',
            enabled=False,
        )
        department = LookupItem(category="department", value="采购合同", sort_order=0)
        department.contract_type_profile = ContractTypeProfile(
            positive_signals_json='["不应加载"]',
        )
        db.add_all((enabled, disabled, department))
        db.commit()

        profiles = load_type_profiles(db, ["采购合同", "销售合同"])

        assert tuple(profiles) == ("采购合同",)
        assert profiles["采购合同"].aliases == ("采购",)
        with pytest.raises(TypeError):
            profiles["采购合同"] = TypeProfile()


@pytest.mark.parametrize("label", ["合同类型", "协议类型", "文件类型"])
def test_explicit_dictionary_value_is_high_weight_evidence(label):
    result = classify_contract_type(
        filename="x.docx",
        text=f"{label}：居间合同\n正文",
        available_types=["居间合同"],
        profiles={},
    )

    assert result.suggested_type == "居间合同"
    assert "explicit_type:居间合同" in result.evidence
    assert result.conflict is False


def test_unknown_explicit_type_is_not_fuzzily_matched():
    result = classify_contract_type(
        filename="x.docx",
        text="合同类型：居间服务合同\n正文",
        available_types=["居间合同"],
        profiles={},
    )

    assert result.suggested_type == ""


@pytest.mark.parametrize(
    "text",
    [
        "\n".join(["正文"] * 40 + ["合同类型：居间合同"]),
        "甲" * 1800 + "\n合同类型：居间合同",
    ],
    ids=["after-40-nonempty-lines", "after-1800-characters"],
)
def test_explicit_type_outside_controlled_header_is_ignored(text):
    result = classify_contract_type(
        filename="x.docx",
        text=text,
        available_types=["居间合同"],
        profiles={},
    )

    assert result.suggested_type == ""


@pytest.mark.parametrize(
    ("filename", "text"),
    [
        ("采购合同.docx", "合同类型：销售合同\n双方约定付款。"),
        ("x.docx", "合同类型：销售合同\n采购人采购设备并要求供货。"),
    ],
    ids=["trusted-title", "strong-trade-signal"],
)
def test_explicit_type_conflict_never_auto_readies(monkeypatch, filename, text):
    result = classify_contract_type(
        filename=filename,
        text=text,
        available_types=["采购合同", "销售合同"],
    )
    monkeypatch.setattr(
        import_service,
        "settings",
        type(
            "Config",
            (),
            {
                "CONTRACT_TYPE_AUTO_READY_ENABLED": True,
                "CONTRACT_TYPE_READY_THRESHOLD": 0.85,
            },
        )(),
    )

    assert result.suggested_type == "销售合同"
    assert {item.contract_type for item in result.candidates} == {
        "采购合同",
        "销售合同",
    }
    assert result.conflict is True
    assert result.confidence == 0.40
    assert result.auto_ready_eligible is False
    assert target_status(
        result.suggested_type,
        result.confidence,
        auto_ready_eligible=result.auto_ready_eligible,
    ) == "awaiting_confirmation"


def test_classifies_purchase_contract_with_high_confidence():
    result = classify_contract_type(
        filename="设备采购合同.pdf",
        text="甲方向乙方采购服务器设备，乙方负责供货和验收。",
        available_types=TYPES,
    )

    assert result.suggested_type == "采购合同"
    assert result.confidence >= 0.85
    assert "采购" in result.evidence


def test_returns_no_selection_when_evidence_is_too_weak():
    result = classify_contract_type(
        filename="扫描件03.pdf",
        text="双方经协商一致订立本文件。",
        available_types=TYPES,
    )

    assert result.suggested_type == ""
    assert result.confidence < 0.60


def test_training_service_agreement_title_overrides_incidental_sales_words():
    result = classify_contract_type(
        filename="F3-025-渠道销售人员培训服务协议.pdf",
        text="渠道销售人员培训服务协议\n合同类型：培训服务协议\n"
             "培训机构提供课程设计和授课，学员为销售经理。",
        available_types=ALL_TYPES,
    )

    assert result.suggested_type == "服务协议"
    assert 0.60 <= result.confidence <= 0.70
    assert result.auto_ready_eligible is False


def test_untrusted_sample_cover_line_does_not_hide_real_agreement_title():
    result = classify_contract_type(
        filename="F3-025-渠道销售人员培训服务协议.pdf",
        text="合成测试样本，仅用于系统验收\n渠道销售人员培训服务协议\n"
             "案例编号：F3-025\n合同类型：培训服务协议\n销售经理参加课程。",
        available_types=ALL_TYPES,
    )

    assert result.suggested_type == "服务协议"
    assert result.confidence < 0.85
    assert result.auto_ready_eligible is False


def test_broad_insurance_service_agreement_title_is_not_auto_certain():
    result = classify_contract_type(
        filename="F3-044-员工补充医疗保险服务协议.pdf",
        text="合成测试样本，仅用于系统验收\n员工补充医疗保险服务协议\n"
             "合同类型：员工保险服务协议\n甲方提供保险服务。",
        available_types=ALL_TYPES,
    )

    assert result.suggested_type == "服务协议"
    assert result.confidence <= 0.70
    assert result.auto_ready_eligible is False


def test_only_returns_an_available_contract_type():
    result = classify_contract_type(
        filename="系统开发协议.docx",
        text="交付源代码并完成软件系统开发。",
        available_types=["技术开发合同", "采购合同"],
    )

    assert result.suggested_type == "技术开发合同"


@pytest.mark.parametrize("contract_type", ALL_TYPES)
def test_every_configured_type_is_reachable_by_its_title(contract_type):
    result = classify_contract_type(
        filename=f"{contract_type}.pdf", text=f"{contract_type}\n甲乙双方订立本合同。",
        available_types=ALL_TYPES,
    )

    assert result.suggested_type == contract_type
    assert result.candidates[0].contract_type == contract_type
    assert result.candidates[0].score > 0
    assert len(result.candidates) <= 3
    assert result.auto_ready_eligible is True


def test_filename_trade_signal_outweighs_generic_confidentiality_clause():
    result = classify_contract_type(
        filename="设备采购合同.pdf",
        text="双方对商业秘密承担保密义务，违反约定承担违约责任，争议协商解决。",
        available_types=ALL_TYPES,
    )

    assert result.suggested_type == "采购合同"
    assert result.candidates[0].contract_type == "采购合同"
    assert all(candidate.score <= 0.25 for candidate in result.candidates if candidate.contract_type == "保密协议")


def test_only_generic_clauses_cannot_become_high_confidence_or_auto_ready():
    result = classify_contract_type(
        filename="扫描件.pdf",
        text="双方承担保密义务，违约责任和争议解决依照本协议约定。",
        available_types=ALL_TYPES,
    )

    assert result.confidence < 0.60
    assert result.auto_ready_eligible is False


def test_candidates_are_stably_sorted_and_exclude_nonpositive_scores():
    result = classify_contract_type(
        filename="扫描件.pdf", text="采购设备并销售产品。", available_types=ALL_TYPES,
    )

    assert result.candidates == tuple(sorted(result.candidates, key=lambda item: (-item.score, item.contract_type)))
    assert all(candidate.score > 0 for candidate in result.candidates)


def test_trade_signal_at_character_300_is_in_lead_not_body():
    result = classify_contract_type(
        filename="扫描件.pdf", text="背景\n" + "甲" * 300 + "采购设备",
        available_types=["采购合同"],
    )

    assert result.candidates[0].score == 3


def test_trade_signal_after_lead_is_only_body_weight():
    result = classify_contract_type(
        filename="扫描件.pdf", text="背景\n" + "甲" * 1800 + "采购设备",
        available_types=["采购合同"],
    )

    assert result.candidates[0].score == 1


@pytest.mark.parametrize(
    "body", ["双方订立本合同。", "背景\n" + "甲" * 1800 + "采购设备"],
    ids=["tied", "near-tied"],
)
def test_tied_or_near_tied_types_cannot_auto_ready(body):
    result = classify_contract_type(
        filename="采购合同-销售合同.pdf", text=body,
        available_types=["采购合同", "销售合同"],
    )

    assert result.candidates[0].score >= 6
    assert result.candidates[1].score >= 6
    assert result.confidence < 0.85
    assert result.auto_ready_eligible is False


@pytest.mark.parametrize("heading", ["保密协议（附件）", "附件：保密协议", "保密协议条款"])
def test_attachment_or_clause_heading_does_not_override_later_trade(heading):
    result = classify_contract_type(
        filename="scan.pdf", text=heading + "\n" + "甲" * 1800 + "采购设备交付",
        available_types=["采购合同", "保密协议"],
    )

    assert result.suggested_type == "采购合同"
    assert result.auto_ready_eligible is False
    assert result.confidence < 0.85


def test_custom_purchase_type_is_reached_by_controlled_trade_alias():
    result = classify_contract_type(
        filename="scan.pdf", text="双方采购设备并约定交付。",
        available_types=["设备采购合同"],
        profiles={
            "设备采购合同": TypeProfile(
                aliases=("采购", "购置"),
                positive_signals=("采购", "设备"),
            )
        },
    )

    assert result.suggested_type == "设备采购合同"
    assert result.candidates[0].score == 3


def test_purchase_order_filename_suggests_available_standard_type_without_auto_ready():
    result = classify_contract_type(
        filename="设备采购订单.pdf", text="双方约定付款期限。",
        available_types=["采购合同", "销售合同", "保密协议"],
    )

    assert result.suggested_type == "采购合同"
    assert result.candidates[0].score == 6
    assert result.auto_ready_eligible is False


@pytest.mark.parametrize("filename", ["保密协议附件.pdf", "保密协议条款.pdf"])
def test_attachment_or_clause_filename_is_only_weak_confidentiality_evidence(filename):
    result = classify_contract_type(
        filename=filename, text="双方对履约中知悉的信息承担普通保密义务。",
        available_types=["保密协议", "采购合同"],
    )

    assert result.suggested_type == "保密协议"
    assert result.candidates[0].score == 0.25
    assert result.confidence < 0.60
    assert result.auto_ready_eligible is False


def test_plain_confidentiality_agreement_filename_remains_trusted():
    result = classify_contract_type(
        filename="保密协议.pdf", text="双方对履约中知悉的信息承担保密义务。",
        available_types=["保密协议", "采购合同"],
    )

    assert result.suggested_type == "保密协议"
    assert result.candidates[0].score >= 6
    assert result.auto_ready_eligible is True


def test_title_and_lead_are_disjoint_while_later_lead_signals_remain():
    result = classify_contract_type(
        filename="scan.pdf", text="采购合同\n销售产品并收取销售货款",
        available_types=["采购合同", "销售合同"],
    )

    assert [(item.contract_type, item.score) for item in result.candidates] == [
        ("采购合同", 6),
        ("销售合同", 3),
    ]
    assert result.confidence < 0.85
    assert result.auto_ready_eligible is False


def test_single_line_narrative_containing_type_remains_lead_evidence():
    result = classify_contract_type(
        filename="scan.pdf", text="本采购合同由乙方向甲方销售产品并收取货款。",
        available_types=["采购合同", "销售合同"],
    )

    assert [(item.contract_type, item.score) for item in result.candidates] == [
        ("采购合同", 3),
        ("销售合同", 3),
    ]
    assert result.confidence < 0.85
    assert result.auto_ready_eligible is False


def test_organization_prefixed_contract_title_remains_trusted():
    result = classify_contract_type(
        filename="scan.pdf", text="浙江某某有限公司设备采购合同\n双方约定付款期限。",
        available_types=["采购合同", "销售合同"],
    )

    assert result.suggested_type == "采购合同"
    assert result.candidates[0].score == 6


@pytest.mark.parametrize(
    "text",
    [
        "本采购合同由乙方向甲方销售产品并收取货款",
        "本采购合同由乙方向甲方销售产品并收取货款.",
    ],
    ids=["no-punctuation", "ascii-period"],
)
def test_unpunctuated_single_line_narrative_is_not_a_title(text):
    result = classify_contract_type(
        filename="scan.pdf", text=text,
        available_types=["采购合同", "销售合同"],
    )

    assert [(item.contract_type, item.score) for item in result.candidates] == [
        ("采购合同", 3),
        ("销售合同", 3),
    ]
    assert result.confidence < 0.85
    assert result.auto_ready_eligible is False


@pytest.mark.parametrize("title", ["采购合同（2026版）", "采购合同V2.1"])
def test_contract_title_allows_common_version_suffixes(title):
    result = classify_contract_type(
        filename="scan.pdf", text=title + "\n双方约定付款期限。",
        available_types=["采购合同", "销售合同"],
    )

    assert result.suggested_type == "采购合同"
    assert result.candidates[0].score == 6


@pytest.mark.parametrize(
    "text",
    ["甲乙双方约定签订采购合同", "乙方向甲方交付设备的采购合同"],
)
def test_party_performance_narrative_ending_in_type_is_not_a_title(text):
    result = classify_contract_type(
        filename="scan.pdf", text=text,
        available_types=["采购合同", "销售合同"],
    )

    assert result.candidates[0].score == 3
    assert result.auto_ready_eligible is False


@pytest.mark.parametrize(
    "text",
    [
        "本项目由供应商销售产品拟签订采购合同",
        "我司向客户销售产品并签订采购合同",
    ],
)
def test_open_ended_narrative_cannot_hide_competing_lead_signal(text):
    result = classify_contract_type(
        filename="scan.pdf", text=text,
        available_types=["采购合同", "销售合同"],
    )

    assert [(item.contract_type, item.score) for item in result.candidates] == [
        ("采购合同", 3),
        ("销售合同", 3),
    ]
    assert result.confidence < 0.85
    assert result.auto_ready_eligible is False


def test_title_candidate_does_not_repeat_matching_lead_score():
    result = classify_contract_type(
        filename="scan.pdf", text="采购合同\n甲方向乙方采购设备并约定交付。",
        available_types=["采购合同", "销售合同"],
    )

    assert result.candidates[0].contract_type == "采购合同"
    assert result.candidates[0].score == 6


def test_filename_and_first_line_same_title_only_score_once():
    result = classify_contract_type(
        filename="采购合同.pdf", text="采购合同\n双方约定付款期限。",
        available_types=["采购合同", "销售合同"],
    )

    assert result.candidates[0].score == 6


@pytest.mark.parametrize("filename", ["采购合同审核说明.pdf", "采购合同模板范本.pdf"])
def test_material_filename_cannot_auto_ready(filename):
    result = classify_contract_type(
        filename=filename, text="双方承担保密义务和违约责任。",
        available_types=["采购合同", "保密协议"],
    )

    assert result.suggested_type != "采购合同" or result.candidates[0].score < 6
    assert result.auto_ready_eligible is False


@pytest.mark.parametrize("title", ["关于选用采购合同", "采购合同复核记录", "采购合同说明"])
def test_material_title_cannot_auto_ready(title):
    result = classify_contract_type(
        filename="scan.pdf", text=title + "\n双方承担保密义务。",
        available_types=["采购合同", "保密协议"],
    )

    assert result.suggested_type != "采购合同" or result.candidates[0].score < 6
    assert result.auto_ready_eligible is False


def test_material_filename_does_not_block_body_trade_candidate():
    result = classify_contract_type(
        filename="采购合同审核说明.pdf", text="甲方采购设备并交付。",
        available_types=["采购合同", "销售合同"],
    )

    assert result.suggested_type == "采购合同"
    assert result.candidates[0].score == 3
    assert result.auto_ready_eligible is False


@pytest.mark.parametrize(
    "filename",
    [
        "采购合同审查报告.pdf",
        "评审报告采购合同.pdf",
        "参考样本采购合同.pdf",
        "补充材料采购合同.pdf",
    ],
)
def test_unstructured_material_filename_never_auto_readies(monkeypatch, filename):
    result = classify_contract_type(
        filename=filename, text="审查正文载明普通保密和违约条款。",
        available_types=["采购合同", "销售合同", "保密协议"],
    )
    monkeypatch.setattr(
        import_service,
        "settings",
        type("Config", (), {
            "CONTRACT_TYPE_AUTO_READY_ENABLED": True,
            "CONTRACT_TYPE_READY_THRESHOLD": 0.85,
        })(),
    )

    assert result.auto_ready_eligible is False
    assert target_status(
        result.suggested_type, result.confidence,
        auto_ready_eligible=result.auto_ready_eligible,
    ) == "awaiting_confirmation"


@pytest.mark.parametrize("filename", ["采购合同.pdf", "某公司采购合同V2.1.pdf"])
def test_structured_contract_filename_remains_trusted(filename):
    result = classify_contract_type(
        filename=filename, text="双方约定付款期限。",
        available_types=["采购合同", "销售合同"],
    )

    assert result.suggested_type == "采购合同"
    assert result.candidates[0].score == 6
    assert result.auto_ready_eligible is True


def test_unstructured_material_filename_keeps_real_body_trade_candidate():
    result = classify_contract_type(
        filename="参考样本采购合同.pdf", text="甲方采购设备并约定交付。",
        available_types=["采购合同", "销售合同"],
    )

    assert result.suggested_type == "采购合同"
    assert result.candidates[0].score >= 3
    assert result.auto_ready_eligible is False


@pytest.mark.parametrize(
    "filename",
    [
        "采购合同（审查报告）.pdf",
        "采购合同（风险清单）.pdf",
        "评审报告项目采购合同.pdf",
        "参考样本工程采购合同.pdf",
    ],
)
def test_material_structure_cannot_masquerade_as_contract_title(monkeypatch, filename):
    result = classify_contract_type(
        filename=filename, text="审查正文包含普通保密条款。",
        available_types=["采购合同", "销售合同", "保密协议"],
    )
    monkeypatch.setattr(
        import_service,
        "settings",
        type("Config", (), {
            "CONTRACT_TYPE_AUTO_READY_ENABLED": True,
            "CONTRACT_TYPE_READY_THRESHOLD": 0.85,
        })(),
    )

    assert result.auto_ready_eligible is False
    assert target_status(
        result.suggested_type, result.confidence,
        auto_ready_eligible=result.auto_ready_eligible,
    ) == "awaiting_confirmation"


@pytest.mark.parametrize(
    "filename",
    [
        "采购合同（2026年）.pdf",
        "采购合同（编号A03-2026）.pdf",
        "采购合同V2.1.pdf",
        "浙江某公司采购合同.pdf",
        "滨江数据中心项目采购合同.pdf",
    ],
)
def test_controlled_suffix_and_named_prefix_contract_titles_remain_trusted(filename):
    result = classify_contract_type(
        filename=filename, text="双方约定付款期限。",
        available_types=["采购合同", "销售合同"],
    )

    assert result.suggested_type == "采购合同"
    assert result.candidates[0].score == 6
    assert result.auto_ready_eligible is True
