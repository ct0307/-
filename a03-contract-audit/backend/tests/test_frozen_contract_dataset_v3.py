from __future__ import annotations

from pathlib import Path
from collections import Counter
from dataclasses import replace
from hashlib import sha256

import pytest

from evaluation.datasets.frozen_contracts_v3.cases import load_cases
from evaluation.datasets.frozen_contracts_v3.models import load_profile


BACKEND_ROOT = Path(__file__).resolve().parents[1]
DATASET_ROOT = BACKEND_ROOT / "evaluation" / "datasets" / "frozen_contracts_v3"


def test_v3_module_is_independent_and_profile_is_fixed():
    profile = load_profile(DATASET_ROOT / "corpus-profile.json")

    assert profile.version == "3.0.0"
    assert profile.valid_count == 50
    assert profile.invalid_count == 2
    assert dict(profile.formats) == {
        "docx": 14,
        "text_pdf": 21,
        "scanned_or_mixed_pdf": 15,
    }
    assert sum(profile.drafting_styles.values()) == 50
    assert len(profile.drafting_styles) == 12

    cases = load_cases()
    assert len(cases) == 50
    source = (DATASET_ROOT / "cases.py").read_text(encoding="utf-8")
    assert "frozen_contracts_v1" not in source
    assert "frozen_contracts_v2" not in source


def test_v3_cases_are_explicit_and_business_complete():
    cases = load_cases()

    assert [case.case_id for case in cases] == [f"F3-{index:03d}" for index in range(1, 51)]
    assert Counter(case.scenario for case in cases) == {
        "procurement": 12,
        "technology": 10,
        "operations": 8,
        "leasing": 6,
        "construction": 5,
        "workforce": 4,
        "data_ip": 3,
        "framework": 2,
    }
    assert Counter(case.format for case in cases) == {
        "docx": 14,
        "text_pdf": 21,
        "pdf": 15,
    }
    assert Counter(case.risk_level for case in cases) == {
        "actionable": 28,
        "negotiated": 14,
        "baseline": 8,
    }
    assert sum(len(case.parties) >= 3 for case in cases) >= 5
    assert sum(case.truth.amount is None for case in cases) >= 10

    for case in cases:
        assert case.title and case.contract_type and case.drafting_style
        assert len(case.parties) >= 2
        assert len({party.role for party in case.parties}) == len(case.parties)
        assert all(party.name and party.address for party in case.parties)
        assert case.truth.subject
        assert case.truth.pricing
        assert case.truth.duration
        assert case.truth.payment_terms
        assert case.truth.delivery
        assert case.truth.acceptance
        assert case.truth.termination
        assert case.annex_types

    source = (DATASET_ROOT / "cases.py").read_text(encoding="utf-8")
    assert "for index in range" not in source
    assert "enumerate(" not in source
    assert source.count("ContractCase(") == 50


def test_v3_styles_have_substantive_differences_and_annexes_match_scenarios():
    from evaluation.datasets.frozen_contracts_v3.annexes import (
        ANNEX_SCHEMAS,
        SCENARIO_ALLOWED_ANNEXES,
        build_annexes,
    )
    from evaluation.datasets.frozen_contracts_v3.clauses import STYLE_PROFILES

    assert len(STYLE_PROFILES) == 12
    signatures = {
        (
            profile.section_order,
            profile.obligation_focus,
            profile.opening_pattern,
            profile.signature_pattern,
        )
        for profile in STYLE_PROFILES.values()
    }
    assert len(signatures) == 12
    assert all(len(profile.section_order) >= 8 for profile in STYLE_PROFILES.values())
    assert all(len(profile.obligation_focus) >= 3 for profile in STYLE_PROFILES.values())

    for case in load_cases():
        annexes = build_annexes(case)
        assert tuple(annex.annex_type for annex in annexes) == case.annex_types
        assert set(case.annex_types) <= SCENARIO_ALLOWED_ANNEXES[case.scenario]
        for annex in annexes:
            assert annex.columns == ANNEX_SCHEMAS[annex.annex_type]
            assert annex.rows and all(len(row) == len(annex.columns) for row in annex.rows)
            assert annex.columns != ("记录项目", "责任方", "业务凭证")


def test_v3_documents_meet_realistic_length_and_obligation_thresholds():
    from evaluation.datasets.frozen_contracts_v3.content import build_contract

    for case in load_cases():
        document = build_contract(case)
        chinese_count = sum("\u4e00" <= char <= "\u9fff" for char in document.plain_text)
        if case.length_class == "short":
            assert 1_200 <= chinese_count <= 1_800, case.case_id
        elif case.length_class == "long":
            assert chinese_count >= 6_000, case.case_id
        else:
            assert chinese_count >= 2_500, case.case_id

        substantive_sections = [section for section in document.sections if section.paragraphs]
        assert len(substantive_sections) >= 10, case.case_id
        paragraphs = [paragraph for section in document.sections for paragraph in section.paragraphs]
        assert len(paragraphs) == len(set(paragraphs)), case.case_id
        assert not hasattr(document, "target_pages")


def test_v3_render_modes_and_revision_xml(tmp_path):
    from zipfile import ZipFile

    import fitz

    from evaluation.datasets.frozen_contracts_v3.content import build_contract
    from evaluation.datasets.frozen_contracts_v3.ooxml import extract_revision_text
    from evaluation.datasets.frozen_contracts_v3.renderers import (
        render_docx,
        render_mixed_pdf,
        render_scanned_pdf,
        render_text_pdf,
    )

    cases = load_cases()
    revision_cases = [case for case in cases if case.revision_set]
    assert len(revision_cases) == 4
    assert all(case.format == "docx" for case in revision_cases)

    revision_case = revision_cases[0]
    docx_path = render_docx(build_contract(revision_case), tmp_path / "redline.docx", case=revision_case)
    with ZipFile(docx_path) as archive:
        document_xml = archive.read("word/document.xml")
        settings_xml = archive.read("word/settings.xml")
        assert b"w:trackRevisions" in settings_xml
        assert b"w:ins" in document_xml and b"w:del" in document_xml
        assert b"w:commentRangeStart" in document_xml
        assert "word/comments.xml" in archive.namelist()
    assert revision_case.revision_set.inserted_text in extract_revision_text(docx_path, accept_changes=True)

    native = next(case for case in cases if case.format == "text_pdf")
    scanned = next(case for case in cases if case.render_mode == "scanned")
    mixed = next(case for case in cases if case.render_mode == "mixed")
    native_path = render_text_pdf(build_contract(native), tmp_path / "native.pdf")
    scanned_path = render_scanned_pdf(build_contract(scanned), tmp_path / "scanned.pdf")
    mixed_path = render_mixed_pdf(build_contract(mixed), tmp_path / "mixed.pdf")
    with fitz.open(native_path) as pdf:
        assert pdf.page_count >= 2
        assert sum(len(page.get_text()) for page in pdf) > 1_000
    with fitz.open(scanned_path) as pdf:
        assert sum(len(page.get_text()) for page in pdf) == 0
        assert all(page.get_images() for page in pdf)
    with fitz.open(mixed_path) as pdf:
        text_lengths = [len(page.get_text()) for page in pdf]
        assert any(length > 0 for length in text_lengths)
        assert any(length == 0 for length in text_lengths)


def test_v3_generation_freezes_50_plus_2_without_overwrite(tmp_path):
    from evaluation.datasets.frozen_contracts_v3.generate import generate_dataset

    v1_cases = BACKEND_ROOT / "evaluation" / "datasets" / "frozen_contracts_v1" / "cases.json"
    v2_cases = BACKEND_ROOT / "evaluation" / "datasets" / "frozen_contracts_v2" / "cases.py"
    before = {path: sha256(path.read_bytes()).hexdigest() for path in (v1_cases, v2_cases)}
    root = tmp_path / "frozen-contracts-v3"

    result = generate_dataset(root)

    assert result.valid_count == 50
    assert result.invalid_count == 2
    assert result.supplemental_count == 1
    assert len(result.manifest["files"]) == 53
    hashes = [row["sha256"] for row in result.manifest["files"]]
    assert len(hashes) == len(set(hashes))
    assert result.manifest["evidence_level"] == "construction_truth_only"
    assert result.manifest["formal_gold"] is False
    with pytest.raises(FileExistsError, match="冻结目录已存在"):
        generate_dataset(root)
    after = {path: sha256(path.read_bytes()).hexdigest() for path in (v1_cases, v2_cases)}
    assert after == before


def test_v3_validator_rejects_sparse_duplicate_or_mismatched_documents():
    from evaluation.datasets.frozen_contracts_v3.content import ContractDocument, build_contract
    from evaluation.datasets.frozen_contracts_v3.validate import validate_contract_documents

    cases = load_cases()
    documents = [build_contract(case) for case in cases]

    sparse = replace(documents[0], sections=documents[0].sections[:1], annexes=())
    reasons = validate_contract_documents(cases, [sparse, *documents[1:]])
    assert any("F3-001" in reason and "正文长度" in reason for reason in reasons)

    duplicate = replace(documents[1], sections=documents[0].sections, annexes=documents[0].annexes)
    reasons = validate_contract_documents(cases, [documents[0], duplicate, *documents[2:]])
    assert any("正文相似度过高" in reason for reason in reasons)

    mismatched_case = replace(cases[0], annex_types=("data_catalog",))
    mismatched_document = build_contract(mismatched_case)
    reasons = validate_contract_documents([mismatched_case], [mismatched_document])
    assert any("F3-001" in reason and "附件与场景不匹配" in reason for reason in reasons)


def test_v3_contract_lengths_stay_within_realistic_ranges():
    from evaluation.datasets.frozen_contracts_v3.content import build_contract

    for case in load_cases():
        count = sum("\u4e00" <= char <= "\u9fff" for char in build_contract(case).plain_text)
        if case.length_class == "standard":
            assert 2_500 <= count <= 5_500, (case.case_id, count)
        elif case.length_class == "long":
            assert 6_000 <= count <= 10_000, (case.case_id, count)


def test_v3_risk_layers_and_conflicts_have_contract_evidence():
    from evaluation.datasets.frozen_contracts_v3.content import build_contract

    cases = load_cases()
    assert sum(bool(case.conflicts) for case in cases) == 6
    for case in cases:
        document = build_contract(case)
        if case.risk_level in {"actionable", "negotiated"}:
            assert "特别责任安排" in document.plain_text, case.case_id
        for conflict in case.conflicts:
            assert conflict.text_a != conflict.text_b
            assert conflict.text_a in document.plain_text
            assert conflict.text_b in document.plain_text
            assert conflict.precedence_rule in document.plain_text
            assert conflict.effective_value in (conflict.text_a + conflict.text_b)


def test_v3_annexes_and_signature_blocks_look_like_business_documents():
    from evaluation.datasets.frozen_contracts_v3.annexes import ANNEX_NAMES, build_annexes
    from evaluation.datasets.frozen_contracts_v3.content import build_contract

    assert all(any("\u4e00" <= char <= "\u9fff" for char in name) for name in ANNEX_NAMES.values())
    for case in load_cases():
        expected_rows = {"short": 3, "standard": 4, "long": 6}[case.length_class]
        assert all(len(annex.rows) == expected_rows for annex in build_annexes(case))
        document = build_contract(case)
        signature = next(section for section in document.sections if section.heading == "签署页")
        assert signature.rows[0] == ("签约方", "授权代表", "签署日期", "盖章位置")
        assert len(signature.rows) == len(case.parties) + 1
