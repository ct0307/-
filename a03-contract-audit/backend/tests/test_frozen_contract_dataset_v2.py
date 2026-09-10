from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from collections import Counter

from evaluation.datasets.frozen_contracts_v2.cases import load_cases
from evaluation.datasets.frozen_contracts_v2.models import load_profile


BACKEND_ROOT = Path(__file__).resolve().parents[1]
DATASET_ROOT = BACKEND_ROOT / "evaluation" / "datasets" / "frozen_contracts_v2"
V1_ROOT = BACKEND_ROOT / "evaluation" / "datasets" / "frozen_contracts_v1"


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
    assert sha256((V1_ROOT / "cases.json").read_bytes()).hexdigest() == (
        "5de4784897ff233f0d123e6eb3b8d5f1c49edbc975b2173c65f85317c081076c"
    )
    assert sha256((V1_ROOT / "corpus-profile.json").read_bytes()).hexdigest() == (
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
