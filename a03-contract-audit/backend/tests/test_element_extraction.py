"""六要素抽取、证据定位与复核状态契约。"""

import json
from io import BytesIO

import pytest
from openpyxl import load_workbook
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.v1.endpoints import contracts
from app.db.session import Base
from app.models.models import Contract, ImportBatch, ImportBatchItem, LookupItem, Risk, User
from app.services.imports.classifier import TypeSuggestion
from app.services.parser.elements import (
    ElementEvidence,
    ElementResult,
    extract_element_result,
    merge_element_review,
)
from app.services.parser.extractor import DocumentBlock, DocumentParseResult, SourceAnchor
from app.services.report.exporter import export_risk_ledger
from app.tasks import import_tasks


def _parsed(*pages: str) -> DocumentParseResult:
    text = "\n".join(pages)
    return DocumentParseResult(
        text=text,
        source="native",
        blocks=tuple(
            DocumentBlock(
                block_id=f"p{page}",
                block_type="page_text",
                text=content,
                anchor=SourceAnchor(page_number=page),
            )
            for page, content in enumerate(pages, start=1)
        ),
    )


def _assert_evidence(result, field: str, *, page: int | None = None) -> None:
    evidence = result.evidence[field]
    items = evidence if isinstance(evidence, list) else [evidence]
    assert items
    for item in items:
        assert isinstance(item, ElementEvidence)
        assert item.raw_text in result.source_text
        assert result.source_text[item.start:item.end] == item.raw_text
        if page is not None:
            assert item.page == page


def test_extracts_core_fields_with_exact_source_evidence():
    result = extract_element_result(_parsed(
        "甲方：之江科技有限公司\n乙方：云栖设备有限公司\n合同标的：企业合同管理平台建设",
        "合同总价为人民币1,286,000元。合同期限自2026-10-1至2027-3-31。",
    ))

    assert result.values == {
        "party_a": "之江科技有限公司",
        "party_b": "云栖设备有限公司",
        "subject": "企业合同管理平台建设",
        "amount": "人民币1,286,000元",
        "duration": "2026-10-1至2027-3-31",
        "payment_terms": [],
    }
    _assert_evidence(result, "party_a", page=1)
    _assert_evidence(result, "party_b", page=1)
    _assert_evidence(result, "subject", page=1)
    _assert_evidence(result, "amount", page=2)
    _assert_evidence(result, "duration", page=2)


@pytest.mark.parametrize(
    ("text", "field", "expected"),
    [
        ("采购方：之江采购有限公司", "party_a", "之江采购有限公司"),
        ("供应方：云栖供应有限公司", "party_b", "云栖供应有限公司"),
        ("委托方：甲公司", "party_a", "甲公司"),
        ("受托方：乙公司", "party_b", "乙公司"),
        ("出租方：甲公司", "party_a", "甲公司"),
        ("承租方：乙公司", "party_b", "乙公司"),
        ("本合同标的为数据治理服务。", "subject", "数据治理服务"),
        ("合同金额：128万元。", "amount", "128万元"),
        ("总价人民币1,286,000元。", "amount", "人民币1,286,000元"),
        ("合同期限：自生效之日起12个月。", "duration", "自生效之日起12个月"),
    ],
)
def test_each_scalar_field_has_a_positive_rule_and_evidence(text, field, expected):
    result = extract_element_result(_parsed(text))

    assert result.values[field] == expected
    _assert_evidence(result, field, page=1)


def test_party_role_does_not_capture_a_cross_line_legal_representative_label():
    result = extract_element_result(_parsed("甲方：\n法定代表人：张三\n乙方：乙公司"))

    assert result.values["party_a"] is None
    assert "party_a" not in result.evidence


def test_material_total_is_not_contract_amount_but_later_strong_contract_total_is():
    result = extract_element_result(_parsed(
        "设备清单总金额100万元，明细以附件为准。\n本合同总价200万元。"
    ))

    assert result.values["amount"] == "200万元"
    assert result.evidence["amount"].validation == "valid"


def test_payment_amount_conflict_requires_review_but_clear_multi_node_schedule_does_not():
    result = extract_element_result(_parsed(
        "付款方式：合同签订后支付30%预付款。\n"
        "付款安排：合同签订后支付50%预付款。"
    ))

    assert result.values["payment_terms"] == [
        "合同签订后支付30%预付款",
        "合同签订后支付50%预付款",
    ]
    assert "payment_terms" in result.review_fields
    assert all(item.validation == "ambiguous" for item in result.evidence["payment_terms"])


def test_unscoped_distinct_reconciliation_and_payment_nodes_remain_valid():
    result = extract_element_result(_parsed(
        "付款安排：\n1. 每月25日前对账；\n2. 确认收票后45日付款。"
    ))

    assert result.values["payment_terms"] == ["每月25日前对账", "确认收票后45日付款"]
    assert "payment_terms" not in result.review_fields
    assert all(item.validation == "valid" for item in result.evidence["payment_terms"])


def test_same_payment_trigger_with_conflicting_percentages_requires_review():
    result = extract_element_result(_parsed(
        "付款安排：合同签订后支付30%。\n"
        "付款方式：合同签订后支付50%。"
    ))

    assert "payment_terms" in result.review_fields
    assert all(
        item.validation == "ambiguous"
        for item in result.evidence["payment_terms"]
    )


def test_long_payment_section_keeps_nodes_after_1200_characters():
    filler = "付款申请资料应完整。" * 130
    result = extract_element_result(_parsed(
        "付款安排：\n1. 合同签订后支付30%；\n"
        f"{filler}\n2. 最终验收后支付70%。"
    ))

    assert result.values["payment_terms"][-1] == "最终验收后支付70%"


@pytest.mark.parametrize(
    "text",
    [
        "违约方应支付违约金100万元，合同采用按订单结算。",
        "赔偿金额为80万元。",
        "履约保证金为20万元。",
        "供应商注册资本1000万元。",
        "设备单价为5万元。",
        "履约保证金（适用于本项目且不可退还）的总金额为20万元。",
        "公司注册资本（登记信息仅用于主体说明）的总金额为1000万元。",
    ],
)
def test_does_not_treat_excluded_money_semantics_as_contract_amount(text):
    result = extract_element_result(_parsed(text))

    assert result.values["amount"] is None
    assert "amount" not in result.evidence


def test_amount_exclusions_use_the_whole_semantic_sentence_before_selecting_total():
    result = extract_element_result(_parsed(
        "本项目履约保证金应在设备全部验收合格且不存在任何未决索赔事项后返还，"
        "双方确认其总金额为100万元。\n"
        "供应商注册资本已经依法足额实缴并连续三年通过年度审计，"
        "该资本总金额为5000万元。\n"
        "本合同总价为人民币1,286,000元。"
    ))

    assert result.values["amount"] == "人民币1,286,000元"
    assert result.evidence["amount"].validation == "valid"
    assert "amount" not in result.review_fields


@pytest.mark.parametrize(
    "text",
    [
        "合同总价为100万元，其中履约保证金为10万元。",
        "合同金额为100万元，违约金按合同金额的20%计算。",
        "合同总价为100万元，不含履约保证金。",
        "不含履约保证金的合同总价为100万元。",
        "扣除履约保证金后，合同总价为100万元。",
        "注册资本仅用于主体说明，合同金额为100万元。",
    ],
)
def test_explicit_contract_total_survives_later_excluded_terms_in_same_sentence(text):
    result = extract_element_result(_parsed(text))

    assert result.values["amount"] == "100万元"
    assert result.evidence["amount"].validation == "valid"


def test_does_not_treat_delivery_or_warranty_period_as_contract_duration():
    result = extract_element_result(_parsed("交付期为30日，质保期为12个月。"))

    assert result.values["duration"] is None
    assert "duration" not in result.evidence


def test_mixed_contract_duration_formats_are_collected_as_ambiguous_candidates():
    result = extract_element_result(_parsed(
        "合同期限自2026-10-1至2027-3-31。合同期限为24个月。"
    ))

    assert result.values["duration"] == "2026-10-1至2027-3-31"
    assert result.evidence["duration"].validation == "ambiguous"
    assert "duration" in result.review_fields


def test_conflicting_party_role_candidates_require_review():
    result = extract_element_result(_parsed("甲方：甲公司\n采购方：乙公司\n乙方：丙公司"))

    assert result.values["party_a"] == "甲公司"
    assert result.evidence["party_a"].validation == "ambiguous"
    assert "party_a" in result.review_fields


def test_review_reason_contains_searchable_element_conflict_phrase():
    parsed = _parsed("甲方：甲公司\n采购方：乙公司")

    requires_review, reason = merge_element_review(parsed, extract_element_result(parsed))

    assert requires_review is True
    assert "关键要素冲突" in reason


def test_document_review_flag_is_preserved_even_without_a_reason():
    parsed = DocumentParseResult("合同正文", "ocr", requires_review=True)

    requires_review, reason = merge_element_review(
        parsed,
        ElementResult(
            values={field: [] if field == "payment_terms" else None for field in (
                "party_a", "party_b", "subject", "amount", "duration", "payment_terms"
            )},
            evidence={},
            review_fields=(),
            source_text=parsed.text,
        ),
    )

    assert requires_review is True
    assert reason is None


def test_payment_terms_are_an_ordered_list_with_per_node_evidence():
    result = extract_element_result(_parsed(
        "付款安排：\n1. 合同签订后支付30%预付款；\n"
        "2. 项目验收后支付60%验收款；\n3. 质保期满支付10%尾款。"
    ))

    assert result.values["payment_terms"] == [
        "合同签订后支付30%预付款",
        "项目验收后支付60%验收款",
        "质保期满支付10%尾款",
    ]
    _assert_evidence(result, "payment_terms", page=1)


def test_collects_all_payment_sections_in_order_and_deduplicates_exact_repeats():
    result = extract_element_result(_parsed(
        "付款方式：合同签订后支付30%预付款。\n"
        "第二条 项目实施\n"
        "付款安排：项目验收后支付70%尾款。\n"
        "附件重申付款方式：合同签订后支付30%预付款。"
    ))

    assert result.values["payment_terms"] == [
        "合同签订后支付30%预付款",
        "项目验收后支付70%尾款",
    ]
    assert [item.raw_text for item in result.evidence["payment_terms"]] == result.values["payment_terms"]


def test_page_lookup_uses_the_block_containing_the_exact_source_range():
    result = extract_element_result(_parsed(
        "甲方：第一页公司\n合同正文",
        "补充条款\n合同金额：300万元",
        "付款条款：验收后支付全部价款。",
    ))

    assert result.evidence["party_a"].page == 1
    assert result.evidence["amount"].page == 2
    assert result.evidence["payment_terms"][0].page == 3


def test_page_lookup_falls_back_to_evidence_inside_a_reformatted_block():
    text = "合同金额：300万元"
    parsed = DocumentParseResult(
        text=text,
        source="native",
        blocks=(DocumentBlock(
            block_id="pdf-line",
            block_type="page_text",
            text="合同 金额：300万元",
            anchor=SourceAnchor(page_number=4),
        ),),
    )

    result = extract_element_result(parsed)

    assert result.evidence["amount"].page == 4


def test_repeated_value_uses_normalized_block_order_to_find_the_correct_page():
    first_page = (
        "本项目履约保证金在不存在未决索赔后返还，双方确认其总金额为100万元。"
    )
    second_page = "本合同总价为100万元。"
    parsed = DocumentParseResult(
        text=f"{first_page}\n{second_page}",
        source="native",
        blocks=(
            DocumentBlock(
                "p1",
                "page_text",
                first_page.replace("总金额", "总 金额"),
                SourceAnchor(page_number=1),
            ),
            DocumentBlock(
                "p2",
                "page_text",
                second_page.replace("合同总价", "合同 总价"),
                SourceAnchor(page_number=2),
            ),
        ),
    )

    result = extract_element_result(parsed)

    evidence = result.evidence["amount"]
    assert result.values["amount"] == "100万元"
    assert evidence.page == 2
    assert result.source_text[evidence.start:evidence.end] == evidence.raw_text


def test_cross_block_duration_is_ambiguous_when_no_single_page_contains_the_range():
    text = "合同期限自2026-10-1至2027-3-31"
    parsed = DocumentParseResult(
        text=text,
        source="native",
        blocks=(
            DocumentBlock("p1", "page_text", "合同期限自2026-10-1至", SourceAnchor(page_number=1)),
            DocumentBlock("p2", "page_text", "2027-3-31", SourceAnchor(page_number=2)),
        ),
    )

    result = extract_element_result(parsed)

    assert result.evidence["duration"].page is None
    assert result.evidence["duration"].validation == "ambiguous"
    assert "duration" in result.review_fields


def test_unmapped_clean_text_evidence_is_ambiguous_not_valid():
    parsed = DocumentParseResult(
        text="合同金额：人民币1,286,000元",
        source="native",
        blocks=(DocumentBlock(
            "garbled",
            "page_text",
            "合同金 额：人民币1,280,000元",
            SourceAnchor(page_number=2),
        ),),
    )

    result = extract_element_result(parsed)

    assert result.evidence["amount"].page is None
    assert result.evidence["amount"].validation == "ambiguous"
    assert "amount" in result.review_fields


def test_amount_and_date_values_normalize_equivalent_spacing_and_separators():
    result = extract_element_result(_parsed(
        "合同金额：人民币 1,286,000 元。合同期限：2026年10月1日至2027年3月31日。"
    ))

    assert result.values["amount"] == "人民币1,286,000元"
    assert result.values["duration"] == "2026-10-1至2027-3-31"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("成交含税价：\n人民币948000元", "人民币948000元"),
        ("暂估采购额：人民币220万元", "人民币220万元"),
        ("定作报酬：人民币1320万元（含税）", "人民币1320万元"),
    ],
)
def test_controlled_amount_aliases_capture_following_bare_money(text, expected):
    result = extract_element_result(_parsed(text))

    assert result.values["amount"] == expected
    _assert_evidence(result, "amount", page=1)


def test_legacy_api_result_retains_signals_when_called_through_structured_result(monkeypatch):
    parsed = _parsed("甲方：甲公司\n签署日期：2026-10-1\n违约责任：按约承担。")
    monkeypatch.setattr(contracts, "extract_document", lambda _path: parsed)
    engine = _db()
    with Session(engine) as db:
        user = User(username="compat", password_hash="x", role="legal", department="法务部")
        db.add(user)
        db.flush()
        contract = Contract(
            filename="compat.txt",
            storage_path="compat.txt",
            uploaded_by=user.id,
            department=user.department,
        )
        db.add(contract)
        db.commit()

        response = contracts.parse_contract(contract.id, db=db, user=user)

        assert response.elements["sign_date"] == "2026-10-1"
        assert response.elements["text_length"] == len(parsed.text)
        assert response.elements["has_breach_clause"] is True
    engine.dispose()


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


def test_sync_parse_merges_document_and_element_review_reasons(monkeypatch, tmp_path):
    engine = _db()
    with Session(engine) as db:
        user = User(username="legal", password_hash="x", role="legal", department="法务部")
        db.add(user)
        db.flush()
        contract = Contract(
            filename="conflict.txt",
            storage_path=str(tmp_path / "conflict.txt"),
            uploaded_by=user.id,
            department=user.department,
        )
        db.add(contract)
        db.commit()
        parsed = _parsed("甲方：甲公司\n采购方：乙公司\n乙方：丙公司")
        parsed = DocumentParseResult(
            text=parsed.text,
            source="ocr",
            ocr_confidence=0.5,
            requires_review=True,
            review_reason="OCR 质量低",
            blocks=parsed.blocks,
        )
        monkeypatch.setattr(contracts, "extract_document", lambda _path: parsed)

        response = contracts.parse_contract(contract.id, db=db, user=user)

        db.refresh(contract)
        assert response.status == "review_required"
        assert response.requires_review is True
        assert response.review_reason == "OCR 质量低；关键要素冲突，请人工确认"
        assert contract.status == "review_required"
        assert json.loads(contract.elements_json)["party_a"] == "甲公司"
    engine.dispose()


def test_sync_parse_keeps_legacy_payment_string_for_api_storage_and_excel(
    monkeypatch,
    tmp_path,
):
    engine = _db()
    with Session(engine) as db:
        user = User(username="report", password_hash="x", role="legal", department="法务部")
        db.add(user)
        db.flush()
        contract = Contract(
            filename="payments.txt",
            storage_path=str(tmp_path / "payments.txt"),
            uploaded_by=user.id,
            department=user.department,
        )
        db.add(contract)
        db.commit()
        monkeypatch.setattr(
            contracts,
            "extract_document",
            lambda _path: _parsed(
                "付款安排：\n1. 合同签订后支付30%预付款；\n2. 验收后支付70%尾款。"
            ),
        )

        response = contracts.parse_contract(contract.id, db=db, user=user)

        db.refresh(contract)
        stored = json.loads(contract.elements_json)
        expected = "合同签订后支付30%预付款；验收后支付70%尾款"
        assert response.elements["payment_terms"] == expected
        assert stored["payment_terms"] == expected
        assert isinstance(stored["payment_terms"], str)

        db.add(Risk(
            contract_id=contract.id,
            level="low",
            category="付款风险",
            original_text="付款条款",
            basis="内部规则",
            suggestion="复核付款节点",
        ))
        db.commit()
        content = export_risk_ledger(db, contract_ids=[contract.id])
        sheet = load_workbook(BytesIO(content), read_only=True).active
        assert sheet.cell(row=2, column=4).value == expected
    engine.dispose()


def test_import_task_marks_contract_review_required_for_element_conflict(monkeypatch, tmp_path):
    engine = _db()
    with Session(engine) as db:
        user = User(username="legal", password_hash="x", role="legal", department="法务部")
        db.add(user)
        db.flush()
        contract = Contract(
            filename="conflict.txt",
            storage_path=str(tmp_path / "conflict.txt"),
            uploaded_by=user.id,
            department=user.department,
        )
        batch = ImportBatch(owner_id=user.id, idempotency_key="element-conflict", total=1)
        batch.items.append(ImportBatchItem(filename=contract.filename, contract=contract, status="queued"))
        db.add(batch)
        db.add(LookupItem(category="contract_type", value="采购合同"))
        db.commit()
        item_id = batch.items[0].id

    monkeypatch.setattr(import_tasks, "SessionLocal", lambda: Session(engine))
    monkeypatch.setattr(
        import_tasks,
        "extract_document",
        lambda _path: _parsed("甲方：甲公司\n采购方：乙公司\n乙方：丙公司"),
    )
    monkeypatch.setattr(
        import_tasks,
        "classify_contract_type",
        lambda **_kwargs: TypeSuggestion("采购合同", 0.99, ["采购"], auto_ready_eligible=True),
    )

    result = import_tasks.parse_import_item.run(item_id)

    with Session(engine) as db:
        item = db.get(ImportBatchItem, item_id)
        assert result["status"] == "awaiting_confirmation"
        assert item.contract.status == "review_required"
        assert item.contract.requires_review is True
        assert item.contract.review_reason == "关键要素冲突，请人工确认"
    engine.dispose()


def test_import_task_persists_legacy_payment_string(monkeypatch, tmp_path):
    engine = _db()
    with Session(engine) as db:
        user = User(username="importer", password_hash="x", role="legal", department="法务部")
        db.add(user)
        db.flush()
        contract = Contract(
            filename="payments.txt",
            storage_path=str(tmp_path / "payments.txt"),
            uploaded_by=user.id,
            department=user.department,
        )
        batch = ImportBatch(owner_id=user.id, idempotency_key="payment-compat", total=1)
        batch.items.append(ImportBatchItem(filename=contract.filename, contract=contract, status="queued"))
        db.add(batch)
        db.add(LookupItem(category="contract_type", value="采购合同"))
        db.commit()
        item_id = batch.items[0].id

    monkeypatch.setattr(import_tasks, "SessionLocal", lambda: Session(engine))
    monkeypatch.setattr(
        import_tasks,
        "extract_document",
        lambda _path: _parsed("付款方式：签订后支付50%；验收后支付50%。"),
    )
    monkeypatch.setattr(
        import_tasks,
        "classify_contract_type",
        lambda **_kwargs: TypeSuggestion("采购合同", 0.99, ["采购"], auto_ready_eligible=True),
    )

    import_tasks.parse_import_item.run(item_id)

    with Session(engine) as db:
        stored_contract = db.get(ImportBatchItem, item_id).contract
        payment_terms = json.loads(stored_contract.elements_json)["payment_terms"]
        assert payment_terms == "签订后支付50%；验收后支付50%"
        assert isinstance(payment_terms, str)
        evidence = json.loads(stored_contract.element_evidence_json)
        assert evidence["schema_version"] == 1
        assert len(evidence["fields"]["payment_terms"]) == 2
    engine.dispose()
