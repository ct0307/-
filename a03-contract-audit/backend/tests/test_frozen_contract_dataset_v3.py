from __future__ import annotations

from pathlib import Path
from collections import Counter

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
