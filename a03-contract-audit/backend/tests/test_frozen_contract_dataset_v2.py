from __future__ import annotations

from hashlib import sha256
from pathlib import Path

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
