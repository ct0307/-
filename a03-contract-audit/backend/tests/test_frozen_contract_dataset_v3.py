from __future__ import annotations

from pathlib import Path

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
