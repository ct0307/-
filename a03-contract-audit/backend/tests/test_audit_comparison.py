"""候选方案必须先通过固定质量门槛，再比较成本、tokens 和延迟。"""
from __future__ import annotations

import math

import pytest

from evaluation.audit_comparison import QUALITY_THRESHOLDS, compare_audit_candidates


def _candidate(name: str, **overrides) -> dict:
    overall = {
        "high_risk_recall": 0.97,
        "false_success_rate": 0.0,
        "final_truncation_rate": 0.0,
        "quote_location_rate": 1.0,
        "invalid_legal_citation_rate": 0.0,
        "risk_recall": 0.92,
        "risk_precision": 0.90,
        "json_valid_rate": 1.0,
        "mean_cost_per_success": 0.05,
        "mean_prompt_tokens": 100.0,
        "mean_completion_tokens": 50.0,
        "p95_latency_ms": 100.0,
    }
    overall.update(overrides)
    return {
        "candidate": name,
        "sample_count": 10,
        "evaluation_basis": "human_gold",
        "input_hashes": {
            "gold_sha256": "a" * 64,
            "predictions_sha256": (name[0].encode().hex() * 64)[:64],
        },
        "overall": overall,
        "cost_evidence_complete": True,
        "cost_metadata": {
            "currency": "CNY",
            "pricing_source": "provider-price-page",
            "pricing_version": "2026-09-01",
        },
        **(
            {
                "experiment": {
                    "group": name,
                    "git_commit": "94c8f9f" if name == "A" else f"{name.lower()}-commit",
                    "change_scope": {
                        "A": "baseline",
                        "B": "output_budget_only",
                        "C": "selective_cascade",
                    }[name],
                    "output_budget": {"A": 1600, "B": 2400, "C": 1600}[name],
                    "frozen_context": {
                        "model_version": "model-v1",
                        "prompt_version": "prompt-v1",
                        "knowledge_base_version": "kb-v1",
                        "dataset_version": "synthetic-v1",
                        "temperature": 0.2,
                        "environment": "test-env",
                    },
                }
            }
            if name in {"A", "B", "C"}
            else {}
        ),
    }


def _abc(**overrides_by_group) -> list[dict]:
    return [
        _candidate(group, **overrides_by_group.get(group, {})) for group in ("A", "B", "C")
    ]


def test_comparison_rejects_cheaper_candidate_below_quality_gate():
    result = compare_audit_candidates(
        _abc(
            A={"high_risk_recall": 0.80, "mean_cost_per_success": 0.01},
            B={"high_risk_recall": 0.97, "mean_cost_per_success": 0.05},
            C={"high_risk_recall": 0.97, "mean_cost_per_success": 0.06},
        )
    )

    assert result.selected == "B"
    assert result.status == "passed"
    assert result.rejected["A"] == ["high_risk_recall"]
    assert result.evaluation_basis == "human_gold"


def test_comparison_makes_no_claim_when_no_candidate_passes():
    result = compare_audit_candidates(
        _abc(A={"false_success_rate": 0.1}, B={"false_success_rate": 0.1}, C={"false_success_rate": 0.1})
    )

    assert result.selected is None
    assert result.status == "failed"


def test_fixed_gate_contains_exactly_the_eight_planned_thresholds():
    assert list(QUALITY_THRESHOLDS) == [
        "high_risk_recall",
        "false_success_rate",
        "final_truncation_rate",
        "quote_location_rate",
        "invalid_legal_citation_rate",
        "risk_recall",
        "risk_precision",
        "json_valid_rate",
    ]


def test_missing_quality_denominator_fails_the_gate():
    candidates = _abc(A={"high_risk_recall": None})
    candidates[1]["overall"]["false_success_rate"] = 0.1
    candidates[2]["overall"]["false_success_rate"] = 0.1
    result = compare_audit_candidates(candidates)

    assert result.status == "failed"
    assert result.rejected["A"] == ["high_risk_recall"]


@pytest.mark.parametrize(
    "missing",
    [
        "mean_cost_per_success",
        "mean_prompt_tokens",
        "mean_completion_tokens",
        "p95_latency_ms",
    ],
)
def test_missing_key_cost_metric_makes_selection_inconclusive(missing):
    candidates = _abc()
    candidates[0]["overall"][missing] = None

    result = compare_audit_candidates(candidates)

    assert result.status == "quality_passed_cost_inconclusive"
    assert result.selected is None
    assert result.quality_passed == ["A", "B", "C"]


def test_incomplete_pricing_provenance_makes_selection_inconclusive():
    candidates = _abc()
    del candidates[0]["cost_metadata"]["pricing_version"]

    result = compare_audit_candidates(candidates)

    assert result.status == "quality_passed_cost_inconclusive"
    assert result.selected is None


def test_ranking_uses_cost_then_total_tokens_then_p95_then_name():
    result = compare_audit_candidates(
        _abc(
            A={"mean_cost_per_success": 0.05, "mean_prompt_tokens": 90},
            B={"mean_cost_per_success": 0.04, "mean_prompt_tokens": 80, "p95_latency_ms": 110},
            C={"mean_cost_per_success": 0.04, "mean_prompt_tokens": 80, "p95_latency_ms": 90},
        )
    )

    assert result.selected == "C"
    assert result.ranking == ["C", "B", "A"]


def test_duplicate_names_and_non_finite_or_bool_metrics_are_rejected():
    duplicate = compare_audit_candidates(
        [_candidate("A"), _candidate("A"), _candidate("C")]
    )
    assert duplicate.status == "failed"
    assert duplicate.selected is None
    assert "candidate_name_duplicate" in duplicate.contract_errors

    with pytest.raises(ValueError, match="high_risk_recall"):
        compare_audit_candidates(_abc(A={"high_risk_recall": math.nan}))

    with pytest.raises(ValueError, match="mean_prompt_tokens"):
        compare_audit_candidates(_abc(A={"mean_prompt_tokens": True}))

    rejected = _abc(A={"high_risk_recall": 0.5, "mean_cost_per_success": math.inf})
    with pytest.raises(ValueError, match="mean_cost_per_success"):
        compare_audit_candidates(rejected)


@pytest.mark.parametrize(
    ("group", "bad_commit"),
    [
        ("B", None),
        ("B", "__missing__"),
        ("B", {}),
        ("B", ""),
        ("C", "   "),
        ("C", None),
    ],
)
def test_b_and_c_require_nonempty_string_git_commits(group, bad_commit):
    candidates = _abc()
    target = next(item for item in candidates if item["candidate"] == group)
    if bad_commit == "__missing__":
        target["experiment"].pop("git_commit")
    else:
        target["experiment"]["git_commit"] = bad_commit

    result = compare_audit_candidates(candidates)

    assert result.status == "failed"
    assert result.selected is None
    assert "git_commit" in " ".join(result.contract_errors)


def test_empty_candidate_set_is_rejected():
    with pytest.raises(ValueError, match="不能为空"):
        compare_audit_candidates([])


@pytest.mark.parametrize(
    "candidates",
    [
        [_candidate("A"), _candidate("B"), _candidate("C"), _candidate("D")],
        [_candidate("A"), _candidate("B")],
        [_candidate("cheap"), _candidate("reliable"), _candidate("other")],
    ],
)
def test_formal_comparison_rejects_any_candidate_set_other_than_abc(candidates):
    result = compare_audit_candidates(candidates)

    assert result.status == "failed"
    assert result.selected is None
    assert "candidate_set" in result.contract_errors


def test_missing_or_bad_experiment_metadata_cannot_select_candidate():
    missing = _abc()
    del missing[1]["experiment"]
    result = compare_audit_candidates(missing)
    assert result.status == "failed"
    assert result.selected is None
    assert "experiment" in " ".join(result.contract_errors)

    bad_baseline = _abc()
    bad_baseline[0]["experiment"]["git_commit"] = "wrong"
    result = compare_audit_candidates(bad_baseline)
    assert result.status == "failed"
    assert result.selected is None
    assert "94c8f9f" in " ".join(result.contract_errors)

    fake_budget_only = _abc()
    fake_budget_only[1]["experiment"]["output_budget"] = 1600
    result = compare_audit_candidates(fake_budget_only)
    assert result.status == "failed"
    assert result.selected is None
    assert "output_budget" in " ".join(result.contract_errors)


def test_evaluation_basis_must_exist_be_known_and_match_for_all_candidates():
    for mutate in (
        lambda candidates: candidates[0].pop("evaluation_basis"),
        lambda candidates: candidates[0].update(evaluation_basis="construction_truth"),
        lambda candidates: candidates[0].update(evaluation_basis="synthetic"),
    ):
        candidates = _abc()
        mutate(candidates)
        result = compare_audit_candidates(candidates)
        assert result.status == "failed"
        assert result.selected is None
        assert "evaluation_basis" in result.contract_errors


def test_candidates_must_use_the_same_gold_dataset_and_sample_count():
    candidates = _abc()
    candidates[1]["input_hashes"]["gold_sha256"] = "f" * 64
    with pytest.raises(ValueError, match="同一金标准"):
        compare_audit_candidates(candidates)

    candidates = _abc()
    candidates[1]["sample_count"] = 11
    with pytest.raises(ValueError, match="sample_count"):
        compare_audit_candidates(candidates)


def test_candidates_with_different_pricing_basis_are_not_ranked():
    candidates = _abc()
    candidates[1]["cost_metadata"]["currency"] = "USD"

    with pytest.raises(ValueError, match="计价口径"):
        compare_audit_candidates(candidates)


def test_abc_baseline_metadata_is_frozen_and_consistent():
    frozen = {
        "model_version": "model-v1",
        "prompt_version": "prompt-v2",
        "knowledge_base_version": "kb-v3",
        "dataset_version": "synthetic-v4",
        "temperature": 0.2,
        "environment": "win-cpu",
    }
    a = _candidate("A")
    b = _candidate("B")
    c = _candidate("C")
    a["experiment"] = {
        "group": "A",
        "git_commit": "94c8f9f",
        "change_scope": "baseline",
        "output_budget": 1600,
        "frozen_context": frozen,
    }
    b["experiment"] = {
        "group": "B",
        "git_commit": "temporary-eval-config",
        "change_scope": "output_budget_only",
        "output_budget": 2400,
        "frozen_context": frozen,
    }
    c["experiment"] = {
        "group": "C",
        "git_commit": "current",
        "change_scope": "selective_cascade",
        "output_budget": 1600,
        "frozen_context": frozen,
    }

    assert compare_audit_candidates([a, b, c]).status == "passed"

    a["experiment"]["git_commit"] = "wrong"
    result = compare_audit_candidates([a, b, c])
    assert result.status == "failed"
    assert result.selected is None
    assert "94c8f9f" in " ".join(result.contract_errors)

    a["experiment"]["git_commit"] = "94c8f9f"
    a["experiment"]["frozen_context"]["model_version"] = {"prompt": "secret"}
    result = compare_audit_candidates([a, b, c])
    assert result.status == "failed"
    assert "model_version" in " ".join(result.contract_errors)


def test_abc_frozen_context_must_be_identical():
    candidates = [_candidate(group) for group in "ABC"]
    scopes = {"A": "baseline", "B": "output_budget_only", "C": "selective_cascade"}
    for item in candidates:
        group = item["candidate"]
        item["experiment"] = {
            "group": group,
            "git_commit": "94c8f9f" if group == "A" else group.lower(),
            "change_scope": scopes[group],
            "output_budget": {"A": 1600, "B": 2400, "C": 1600}[group],
            "frozen_context": {
                "model_version": "same",
                "prompt_version": "same",
                "knowledge_base_version": "same",
                "dataset_version": "same" if group != "C" else "different",
                "temperature": 0.2,
                "environment": "same",
            },
        }

    result = compare_audit_candidates(candidates)
    assert result.status == "failed"
    assert result.selected is None
    assert "同一冻结上下文" in " ".join(result.contract_errors)
