from app.llm.base import LLMResponse


def test_detects_blank_payment_terms_and_personal_injury_waiver_from_pdf_text():
    from app.services.audit.deterministic_checks import find_deterministic_findings

    text = (
        "（三）甲⽅于每⽉  ⽇前以  ⽅式⽀付上⽉劳务费⽤。\n"
        "（⼆）⼄⽅确认：甲⽅不承担⼄⽅在提供劳务过程中的⼯伤、意外伤害等任何责任，⼄⽅应\n"
        "⾃⾏做好安全防护⼯作。"
    )

    findings = find_deterministic_findings(text)

    assert [finding.category for finding in findings] == [
        "付款日期及方式缺失",
        "人身损害免责责任风险",
    ]
    assert all(finding.quote in text for finding in findings)


def test_detects_blank_party_and_work_scope_but_not_completed_fields():
    from app.services.audit.deterministic_checks import find_deterministic_findings

    incomplete = (
        "⼄⽅（承包⽅）：\n"
        "⾝份证号码：\n"
        "甲⽅将  项⽬的部分劳务⼯作交由⼄⽅完成"
    )
    complete = (
        "乙方（承包方）：张三\n"
        "身份证号码：420100199001010000\n"
        "甲方将道路养护项目的部分劳务工作交由乙方完成"
    )

    assert [item.category for item in find_deterministic_findings(incomplete)] == [
        "合同主体信息缺失",
        "工作范围约定缺失",
    ]
    assert find_deterministic_findings(complete) == []


def test_detects_pdf_blanks_split_across_lines_and_preserves_exact_quote():
    from app.services.audit.deterministic_checks import find_deterministic_findings

    text = (
        "甲方将 \n 项目的部分劳务工作交由乙方完成\n"
        "（三）甲方于每月 \n 日前以 \n 方式支付上月劳务费用。"
    )

    findings = find_deterministic_findings(text)

    assert [finding.category for finding in findings] == [
        "工作范围约定缺失",
        "付款日期及方式缺失",
    ]
    assert all(finding.quote in text for finding in findings)


def test_selected_dimensions_filter_deterministic_findings():
    from app.services.audit.deterministic_checks import find_deterministic_findings

    text = (
        "甲方于每月  日前以  方式支付劳务费用。\n"
        "甲方不承担乙方在提供劳务过程中的工伤、意外伤害等任何责任。"
    )

    payment = find_deterministic_findings(text, dimensions=["payment"])

    assert [finding.category for finding in payment] == ["付款日期及方式缺失"]


def test_deterministic_risk_is_published_with_exact_source_when_model_finds_none(
    monkeypatch,
):
    from app.services.audit import auditor

    class Adapter:
        def chat(self, *_args, **_kwargs):
            return LLMResponse(
                text='{"risks": [], "has_more": false}', model="test"
            )

    text = "第三条 甲方于每月  日前以  方式支付劳务费用。"
    monkeypatch.setattr(auditor, "get_llm_adapter", lambda: Adapter())
    monkeypatch.setattr(auditor, "retrieve", lambda *_args, **_kwargs: [])

    result = auditor.audit_contract({}, text, dimensions=["payment"])

    risk = next(item for item in result["risks"] if item["category"] == "付款日期及方式缺失")
    assert risk["original_text"] in text
    assert risk["original_text_verified"] is True
    assert risk["source_window_id"].startswith("window-")
    assert risk["source_clause_ids"] == ["第三条"]


def test_model_and_deterministic_match_is_published_once(monkeypatch):
    from app.services.audit import auditor

    text = "第三条 甲方于每月  日前以  方式支付劳务费用。"

    class Adapter:
        def chat(self, system, *_args, **_kwargs):
            if "补全单条" in system:
                return LLMResponse(
                    text=(
                        '{"reason":"付款条件缺失。",'
                        '"suggestion":"补充付款日期和方式。"}'
                    ),
                    model="test",
                )
            return LLMResponse(
                text=(
                    '{"risks":[{"level":"medium",'
                    '"category":"付款日期及方式缺失",'
                    f'"quote":"{text}"}}],"has_more":false}}'
                ),
                model="test",
            )

    monkeypatch.setattr(auditor, "get_llm_adapter", lambda: Adapter())
    monkeypatch.setattr(auditor, "retrieve", lambda *_args, **_kwargs: [])

    result = auditor.audit_contract({}, text, dimensions=["payment"])
    matching = [
        risk
        for risk in result["risks"]
        if risk["category"] == "付款日期及方式缺失"
        and risk["original_text"] == text
    ]

    assert len(matching) == 1
