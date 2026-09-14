"""六要素抽取、证据定位与复核状态契约。"""

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.v1.endpoints import contracts
from app.db.session import Base
from app.models.models import Contract, ImportBatch, ImportBatchItem, LookupItem, User
from app.services.imports.classifier import TypeSuggestion
from app.services.parser.elements import (
    ElementEvidence,
    ElementResult,
    extract_element_result,
    merge_element_review,
)
from app.services.parser.extractor import DocumentBlock, DocumentParseResult, SourceAnchor
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


@pytest.mark.parametrize(
    "text",
    [
        "违约方应支付违约金100万元，合同采用按订单结算。",
        "赔偿金额为80万元。",
        "履约保证金为20万元。",
        "供应商注册资本1000万元。",
        "设备单价为5万元。",
    ],
)
def test_does_not_treat_excluded_money_semantics_as_contract_amount(text):
    result = extract_element_result(_parsed(text))

    assert result.values["amount"] is None
    assert "amount" not in result.evidence


def test_does_not_treat_delivery_or_warranty_period_as_contract_duration():
    result = extract_element_result(_parsed("交付期为30日，质保期为12个月。"))

    assert result.values["duration"] is None
    assert "duration" not in result.evidence


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
