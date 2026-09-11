from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from zipfile import ZipFile

import fitz
import pytest

from collections import Counter

from evaluation.datasets.frozen_contracts_v2.cases import load_cases
from evaluation.datasets.frozen_contracts_v2.build_predictions import build_predictions
from evaluation.datasets.frozen_contracts_v2.content import build_contract
from evaluation.datasets.frozen_contracts_v2.generate import generate_dataset
from evaluation.datasets.frozen_contracts_v2.models import load_profile
from evaluation.datasets.frozen_contracts_v2.ooxml import extract_revision_text
from evaluation.datasets.frozen_contracts_v2.precheck import evaluate_construction_truth
from evaluation.datasets.frozen_contracts_v2.renderers import (
    render_docx,
    render_mixed_pdf,
    render_scanned_pdf,
    render_text_pdf,
)
from evaluation.datasets.frozen_contracts_v2.validate import validate_dataset


BACKEND_ROOT = Path(__file__).resolve().parents[1]
DATASET_ROOT = BACKEND_ROOT / "evaluation" / "datasets" / "frozen_contracts_v2"
V1_ROOT = BACKEND_ROOT / "evaluation" / "datasets" / "frozen_contracts_v1"


def _normalized_sha256(path: Path) -> str:
    """统一换行后计算冻结数据指纹，避免 Windows autocrlf 影响验收。"""
    return sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def test_v2_profile_is_fixed_and_v1_facts_are_unchanged():
    profile = load_profile(DATASET_ROOT / "corpus-profile.json")

    assert profile.version == "2.0.0"
    assert profile.valid_count == 50
    assert profile.invalid_count == 2
    assert dict(profile.formats) == {
        "docx": 14,
        "text_pdf": 21,
        "scanned_or_mixed_pdf": 15,
    }
    assert sum(profile.drafting_styles.values()) == 50
    assert len(profile.drafting_styles) == 12
    assert dict(profile.risk_levels) == {
        "actionable": 28,
        "negotiated": 14,
        "baseline": 8,
    }
    assert _normalized_sha256(V1_ROOT / "cases.json") == (
        "5de4784897ff233f0d123e6eb3b8d5f1c49edbc975b2173c65f85317c081076c"
    )
    assert _normalized_sha256(V1_ROOT / "corpus-profile.json") == (
        "782ecb750e4aa0f057d495d25ff16a418b339fb4072438da6d8ec93c9ba612c4"
    )


def test_v2_cases_contain_real_risks_conflicts_annexes_and_revisions():
    cases = load_cases()

    assert [case.case_id for case in cases] == [f"F2-{index:03d}" for index in range(1, 51)]
    assert Counter(case.drafting_style for case in cases) == {
        "buyer_standard": 6,
        "supplier_standard": 5,
        "business_draft": 5,
        "legal_redline": 4,
        "model_contract": 5,
        "online_terms": 3,
        "framework_order": 4,
        "master_supplement": 4,
        "project_conditions": 4,
        "industry_template": 3,
        "customer_template": 4,
        "short_order": 3,
    }
    assert Counter(case.risk_level for case in cases) == {
        "actionable": 28,
        "negotiated": 14,
        "baseline": 8,
    }
    assert sum(bool(case.annexes) for case in cases) >= 30
    assert sum(len(case.parties) >= 3 for case in cases) >= 5
    assert sum(bool(case.conflicts) for case in cases) == 6
    assert sum(case.revision_set is not None for case in cases) == 4
    for case in cases:
        if case.risk_level == "actionable":
            assert case.risk_clauses
            assert all(len(clause.text) >= 24 for clause in case.risk_clauses)
            assert all("建议" not in clause.text and "应当关注" not in clause.text for clause in case.risk_clauses)
        for conflict in case.conflicts:
            assert conflict.text_a != conflict.text_b
            assert conflict.effective_value in (conflict.text_a + conflict.text_b)


def test_v2_rendered_content_contains_declared_evidence_and_distinct_styles():
    cases = load_cases()
    documents = [build_contract(case) for case in cases]
    style_signatures: dict[str, tuple[str, ...]] = {}

    for case, document in zip(cases, documents, strict=True):
        assert "履约控制与证据清单" not in document.plain_text
        for risk in case.risk_clauses:
            assert risk.text in document.plain_text
        for conflict in case.conflicts:
            assert conflict.text_a in document.plain_text
            assert conflict.text_b in document.plain_text
        style_signatures.setdefault(
            case.drafting_style,
            tuple(section.heading for section in document.sections[:5]),
        )

    assert len(style_signatures) == 12
    assert len(set(style_signatures.values())) == 12


def test_v2_docx_contains_real_revisions_and_comments(tmp_path):
    cases = [case for case in load_cases() if case.revision_set]
    assert len(cases) == 4
    for case in cases:
        path = render_docx(build_contract(case), tmp_path / f"{case.case_id}.docx", case=case)
        with ZipFile(path) as archive:
            names = set(archive.namelist())
            document_xml = archive.read("word/document.xml")
            settings_xml = archive.read("word/settings.xml")
            rels_xml = archive.read("word/_rels/document.xml.rels")
            assert b"w:trackRevisions" in settings_xml
            assert b"w:ins" in document_xml and b"w:del" in document_xml
            assert b"w:commentRangeStart" in document_xml
            assert "word/comments.xml" in names
            assert b"/comments" in rels_xml
        all_changes = extract_revision_text(path, accept_changes=False)
        accepted = extract_revision_text(path, accept_changes=True)
        assert case.revision_set.deleted_text in all_changes
        assert case.revision_set.deleted_text not in accepted
        assert case.revision_set.inserted_text in accepted


def test_v2_pdf_render_modes_have_expected_text_layers(tmp_path):
    cases = load_cases()
    native = next(case for case in cases if case.format == "text_pdf")
    scanned = next(case for case in cases if case.render_mode == "scanned")
    mixed = next(case for case in cases if case.render_mode == "mixed")

    native_path = render_text_pdf(build_contract(native), tmp_path / "native.pdf")
    scan_path = render_scanned_pdf(build_contract(scanned), tmp_path / "scan.pdf")
    mixed_path = render_mixed_pdf(build_contract(mixed), tmp_path / "mixed.pdf")
    with fitz.open(native_path) as pdf:
        assert sum(len(page.get_text()) for page in pdf) > 500
    with fitz.open(scan_path) as pdf:
        assert sum(len(page.get_text()) for page in pdf) == 0
        assert all(page.get_images() for page in pdf)
    with fitz.open(mixed_path) as pdf:
        text_lengths = [len(page.get_text()) for page in pdf]
        assert any(length > 0 for length in text_lengths)
        assert any(length == 0 for length in text_lengths)


def test_v2_generation_freezes_50_plus_2_and_rejects_tampering(tmp_path):
    root = tmp_path / "frozen-v2"
    result = generate_dataset(root)
    assert result.valid_count == 50
    assert result.invalid_count == 2
    assert result.supplemental_count == 1
    assert len(result.manifest["files"]) == 53
    hashes = [row["sha256"] for row in result.manifest["files"]]
    assert len(hashes) == len(set(hashes))
    assert validate_dataset(root)["status"] == "passed"
    with pytest.raises(FileExistsError, match="冻结目录已存在"):
        generate_dataset(root)

    first = next((root / "contracts" / "valid").iterdir())
    first.write_bytes(first.read_bytes() + b"tampered")
    with pytest.raises(ValueError, match="SHA-256"):
        validate_dataset(root)


def test_v2_precheck_is_non_formal_and_reports_risk_layers():
    truth = [
        {
            "case_id": f"F2-00{index}",
            "risk_level": level,
            "gold": {"party_a": "甲", "party_b": "乙", "subject": "服务", "amount": None, "duration": "一年", "payment_terms": []},
        }
        for index, level in enumerate(("actionable", "negotiated", "baseline"), start=1)
    ]
    predictions = {row["case_id"]: dict(row["gold"]) for row in truth}
    report = evaluate_construction_truth(truth, predictions)
    assert report["evidence_level"] == "construction_truth_only"
    assert report["formal_gold"] is False
    assert report["threshold_claim"] is None
    assert set(report["by_risk_level"]) == {"actionable", "negotiated", "baseline"}
