"""高拟真合成冻结合同集的画像与生成契约。"""
from collections import Counter
from difflib import SequenceMatcher
import json
from itertools import combinations
from pathlib import Path
import shutil

import fitz
import pytest
from docx import Document

from evaluation.datasets.frozen_contracts_v1.content import build_contract
from evaluation.datasets.frozen_contracts_v1.models import load_cases, load_profile
from evaluation.datasets.frozen_contracts_v1.generate import generate_dataset
from evaluation.datasets.frozen_contracts_v1.precheck import evaluate_construction_truth
from evaluation.datasets.frozen_contracts_v1.renderers import (
    ScanProfile,
    render_docx,
    render_mixed_pdf,
    render_scanned_pdf,
    render_text_pdf,
)
from evaluation.datasets.frozen_contracts_v1.validate import validate_dataset


DATASET_ROOT = (
    Path(__file__).parents[1]
    / "evaluation"
    / "datasets"
    / "frozen_contracts_v1"
)


@pytest.fixture(scope="module")
def frozen_dataset(tmp_path_factory):
    root = tmp_path_factory.mktemp("frozen-contracts") / "v1"
    return generate_dataset(root)


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


def test_contract_content_is_realistic_and_driven_by_case_facts():
    cases = load_cases(DATASET_ROOT / "cases.json")
    documents = [build_contract(case) for case in cases]

    assert all(len(document.sections) >= 10 for document in documents)
    assert all(
        len(document.plain_text) >= case.target_pages * 300
        for case, document in zip(cases, documents, strict=True)
    )
    assert all("合成测试样本，仅用于系统验收" in document.plain_text for document in documents)
    assert sum("甲方：" not in document.plain_text for document in documents) >= 20
    assert sum("合同金额：" not in document.plain_text for document in documents) >= 15

    for case, document in zip(cases, documents, strict=True):
        assert tuple(case.parties[:2]) == (
            case.truth["party_a"],
            case.truth["party_b"],
        )
        assert case.case_id in document.plain_text
        assert case.price_model not in document.plain_text
        assert all(party in document.plain_text for party in case.parties)
        assert case.truth["subject"] in document.plain_text
        assert all(tag in document.plain_text for tag in case.risk_tags)
        assert all(name in document.plain_text for name in case.related_documents)
        if case.clause_conflict:
            assert "不一致" in document.plain_text
            assert "优先" in document.plain_text


def test_contract_content_does_not_repeat_one_uniform_template():
    cases = load_cases(DATASET_ROOT / "cases.json")
    texts = [build_contract(case).plain_text for case in cases]
    maximum_similarity = max(
        SequenceMatcher(None, left, right, autojunk=False).ratio()
        for left, right in combinations(texts, 2)
    )

    assert maximum_similarity < 0.92


def test_renderers_create_real_docx_and_three_pdf_modes(tmp_path):
    cases = load_cases(DATASET_ROOT / "cases.json")
    document = build_contract(cases[0])

    docx_path = render_docx(document, tmp_path / "sample.docx")
    text_pdf_path = render_text_pdf(document, tmp_path / "text.pdf")
    scan_pdf_path = render_scanned_pdf(
        document,
        tmp_path / "scan.pdf",
        profile=ScanProfile.light(),
    )
    mixed_pdf_path = render_mixed_pdf(
        document,
        tmp_path / "mixed.pdf",
        profile=ScanProfile.light(),
    )

    word = Document(docx_path)
    assert "合成测试样本" in word.paragraphs[0].text
    assert round(word.sections[0].page_width.mm) == 210
    assert round(word.sections[0].page_height.mm) == 297
    assert "PAGE" in word.sections[0].footer._element.xml
    assert word.tables
    assert word._element.xml.count('w:type="page"') == document.target_pages - 1

    with fitz.open(text_pdf_path) as pdf:
        assert pdf.page_count == document.target_pages
        assert all(page.get_text().strip() for page in pdf)
        assert "合成测试样本" in pdf[0].get_text()
    assert text_pdf_path.stat().st_size < 2_000_000

    with fitz.open(scan_pdf_path) as pdf:
        assert pdf.page_count == document.target_pages
        assert all(not page.get_text().strip() for page in pdf)
        assert all(page.get_images(full=True) for page in pdf)

    with fitz.open(mixed_pdf_path) as pdf:
        text_pages = [bool(page.get_text().strip()) for page in pdf]
        assert pdf.page_count == document.target_pages
        assert any(text_pages)
        assert not all(text_pages)
        assert all(
            page.get_images(full=True)
            for page in pdf
            if not page.get_text().strip()
        )


def test_generate_freezes_exact_50_plus_2_and_refuses_overwrite(frozen_dataset):
    assert frozen_dataset.valid_count == 50
    assert frozen_dataset.invalid_count == 2
    assert len(frozen_dataset.manifest["files"]) == 53
    assert all(len(row["sha256"]) == 64 for row in frozen_dataset.manifest["files"])

    batch = json.loads(
        (frozen_dataset.root / "batch-manifest.json").read_text(encoding="utf-8")
    )
    assert sum(row["role"] == "valid" for row in batch["samples"]) == 50
    assert sum(row["role"] == "invalid" for row in batch["samples"]) == 2

    truth_rows = [
        json.loads(line)
        for line in (frozen_dataset.root / "construction-truth.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    review_rows = [
        json.loads(line)
        for line in (frozen_dataset.root / "gold-review-template.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert len(truth_rows) == len(review_rows) == 50
    assert all("reviewers" not in row for row in truth_rows)
    assert all(row["review_status"] == "pending_human_review" for row in review_rows)

    with pytest.raises(FileExistsError, match="冻结目录已存在"):
        generate_dataset(frozen_dataset.root)


def test_validator_rejects_hash_tampering(tmp_path, frozen_dataset):
    copied_root = tmp_path / "tampered"
    shutil.copytree(frozen_dataset.root, copied_root)
    first = next((copied_root / "contracts" / "valid").iterdir())
    first.write_bytes(first.read_bytes() + b"tampered")

    with pytest.raises(ValueError, match="SHA-256"):
        validate_dataset(copied_root)


def test_construction_precheck_never_claims_formal_gold():
    truth = {
        "case_id": "FC-001",
        "file": "contracts/valid/FC-001.docx",
        "contract_type": "采购合同",
        "document_kind": "docx",
        "gold": {
            "party_a": "甲公司",
            "party_b": "乙公司",
            "subject": "设备采购",
            "amount": "100万元",
            "duration": "12个月",
            "payment_terms": ["验收后付款"],
        },
    }
    report = evaluate_construction_truth(
        [truth],
        {"FC-001": dict(truth["gold"])},
    )

    assert report["evidence_level"] == "construction_truth_only"
    assert report["formal_gold"] is False
    assert report["threshold_claim"] is None
