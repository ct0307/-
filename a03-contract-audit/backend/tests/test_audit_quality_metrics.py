"""合同审查质量评测必须依赖人工裁定匹配，且证据可审计。"""
from __future__ import annotations

import json
import hashlib
import math
from pathlib import Path

import pytest

from evaluation.audit_quality import evaluate_audit_dataset, evaluate_audit_files


def _gold_case(case_id: str = "c-1", *, risks: list[dict] | None = None) -> dict:
    return {
        "case_id": case_id,
        "evaluation_basis": "human_gold",
        "reviewers": ["legal-reviewer-a", "legal-reviewer-b"],
        "review_status": "agreed",
        "risks": risks
        if risks is not None
        else [
            {
                "gold_risk_id": f"{case_id}-g-1",
                "severity": "high",
                "category": "payment",
                "location": {"clause_id": "clause-7", "start": 10, "end": 18},
                "evidence_ids": ["LAW-509"],
            }
        ],
    }


def _prediction(
    case_id: str = "c-1",
    *,
    status: str = "done",
    risks: list[dict] | None = None,
    finish_reasons: list[str] | None = None,
    coverage: tuple[int, int] = (2, 2),
    complete_cost: bool = True,
) -> dict:
    calls = [
        {
            "json_valid": True,
            "prompt_tokens": 100,
            "completion_tokens": 40,
            "latency_ms": 25,
            **({"cost": 0.012} if complete_cost else {}),
        }
    ]
    return {
        "case_id": case_id,
        "status": status,
        "risks": risks
        if risks is not None
        else [
            {
                "candidate_id": f"{case_id}-p-1",
                "matched_gold_id": f"{case_id}-g-1",
                "quote_located": True,
                "invalid_legal_citation": False,
            }
        ],
        "finish_reasons": finish_reasons or ["stop"],
        "coverage": {"completed": coverage[0], "total": coverage[1]},
        "calls": calls,
        **(
            {
                "currency": "CNY",
                "pricing_source": "provider-price-page",
                "pricing_version": "2026-09-01",
            }
            if complete_cost
            else {}
        ),
    }


def test_false_success_counts_done_with_truncation_or_incomplete_coverage():
    report = evaluate_audit_dataset(
        gold=[_gold_case()],
        predictions=[
            _prediction(finish_reasons=["length"], coverage=(1, 2))
        ],
    )

    assert report["overall"]["false_success_rate"] == 1.0
    assert report["overall"]["final_truncation_rate"] == 1.0
    assert report["overall"]["mean_cost_per_success"] is None


def test_quality_metrics_are_computed_from_explicit_human_matches():
    report = evaluate_audit_dataset(
        gold=[_gold_case()],
        predictions=[
            _prediction(
                risks=[
                    {
                        "candidate_id": "p-1",
                        "matched_gold_id": "c-1-g-1",
                        "quote_located": True,
                        "invalid_legal_citation": False,
                    },
                    {
                        "candidate_id": "p-2",
                        "matched_gold_id": None,
                        "quote_located": False,
                        "invalid_legal_citation": True,
                    },
                ]
            )
        ],
    )

    assert report["overall"] == {
        "high_risk_recall": 1.0,
        "risk_recall": 1.0,
        "risk_precision": 0.5,
        "quote_location_rate": 0.5,
        "invalid_legal_citation_rate": 0.5,
        "json_valid_rate": 1.0,
        "final_truncation_rate": 0.0,
        "false_success_rate": 0.0,
        "manual_review_rate": 0.0,
        "mean_prompt_tokens": 100.0,
        "mean_completion_tokens": 40.0,
        "mean_cost_per_success": 0.012,
        "p95_latency_ms": 25.0,
    }
    assert report["sample_count"] == 1
    assert report["cases"][0]["case_id"] == "c-1"
    assert "risks" not in report["cases"][0]


def test_zero_denominators_are_none_instead_of_claiming_zero_or_one():
    report = evaluate_audit_dataset(
        gold=[_gold_case(risks=[])],
        predictions=[_prediction(risks=[], status="review_required")],
    )

    assert report["overall"]["high_risk_recall"] is None
    assert report["overall"]["risk_recall"] is None
    assert report["overall"]["risk_precision"] is None
    assert report["overall"]["quote_location_rate"] is None
    assert report["overall"]["invalid_legal_citation_rate"] is None
    assert report["overall"]["false_success_rate"] is None
    assert report["overall"]["manual_review_rate"] == 1.0


@pytest.mark.parametrize(
    "mutate,match",
    [
        (
            lambda predictions: predictions[0]["risks"].append(
                {
                    "candidate_id": "p-duplicate",
                    "matched_gold_id": "c-1-g-1",
                    "quote_located": True,
                    "invalid_legal_citation": False,
                }
            ),
            "重复匹配",
        ),
        (
            lambda predictions: predictions[0]["risks"][0].update(
                matched_gold_id="unknown"
            ),
            "未知 gold_risk_id",
        ),
    ],
)
def test_rejects_duplicate_or_unknown_human_matches(mutate, match):
    predictions = [_prediction()]
    mutate(predictions)

    with pytest.raises(ValueError, match=match):
        evaluate_audit_dataset(gold=[_gold_case()], predictions=predictions)


@pytest.mark.parametrize(
    "field,bad_value",
    [
        ("severity", ""),
        ("category", ""),
        ("location", {}),
        ("evidence_ids", []),
    ],
)
def test_gold_risks_require_stable_id_level_category_location_and_evidence(
    field, bad_value
):
    gold = _gold_case()
    gold["risks"][0][field] = bad_value

    with pytest.raises(ValueError, match=field):
        evaluate_audit_dataset(gold=[gold], predictions=[_prediction()])


def test_prediction_requires_explicit_matched_gold_id_even_when_null():
    prediction = _prediction()
    del prediction["risks"][0]["matched_gold_id"]

    with pytest.raises(ValueError, match="matched_gold_id"):
        evaluate_audit_dataset(gold=[_gold_case()], predictions=[prediction])


def test_human_gold_requires_two_independent_reviewers():
    gold = _gold_case()
    gold["reviewers"] = ["only-one"]

    with pytest.raises(ValueError, match="reviewers"):
        evaluate_audit_dataset(gold=[gold], predictions=[_prediction()])


def test_incomplete_pricing_metadata_disables_cost_conclusion():
    report = evaluate_audit_dataset(
        gold=[_gold_case()],
        predictions=[_prediction(complete_cost=False)],
    )

    assert report["overall"]["mean_cost_per_success"] is None
    assert report["cost_evidence_complete"] is False


@pytest.mark.parametrize("status", ["audit_failed", "failed"])
def test_failed_status_cannot_reuse_stale_risks_as_true_positives(status):
    with pytest.raises(ValueError, match="失败状态不得携带风险"):
        evaluate_audit_dataset(
            gold=[_gold_case()],
            predictions=[_prediction(status=status)],
        )


def test_successful_contract_without_calls_has_incomplete_cost_evidence():
    prediction = _prediction()
    prediction["calls"] = []

    report = evaluate_audit_dataset(gold=[_gold_case()], predictions=[prediction])

    assert report["cost_evidence_complete"] is False
    assert report["overall"]["mean_cost_per_success"] is None


def test_rejects_bool_and_non_finite_numeric_observations():
    prediction = _prediction()
    prediction["calls"][0]["prompt_tokens"] = True
    with pytest.raises(ValueError, match="prompt_tokens"):
        evaluate_audit_dataset(gold=[_gold_case()], predictions=[prediction])

    prediction = _prediction()
    prediction["calls"][0]["latency_ms"] = math.nan
    with pytest.raises(ValueError, match="latency_ms"):
        evaluate_audit_dataset(gold=[_gold_case()], predictions=[prediction])

    prediction = _prediction()
    prediction["experiment"] = {
        "group": "C",
        "git_commit": "current",
        "change_scope": "selective_cascade",
        "output_budget": 1600,
        "frozen_context": {
            "model_version": "model-v1",
            "prompt_version": "prompt-v1",
            "knowledge_base_version": "kb-v1",
            "dataset_version": "data-v1",
            "temperature": math.inf,
            "environment": "test",
        },
    }
    with pytest.raises(ValueError, match="temperature"):
        evaluate_audit_dataset(gold=[_gold_case()], predictions=[prediction])


def test_file_evaluation_hashes_exact_inputs_without_storing_sensitive_text(tmp_path):
    gold_path = tmp_path / "gold.jsonl"
    predictions_path = tmp_path / "predictions.jsonl"
    gold_path.write_text(
        json.dumps(_gold_case(), ensure_ascii=False) + "\n", encoding="utf-8"
    )
    prediction = _prediction()
    prediction["contract_text"] = "不应进入评测报告的合同正文"
    prediction["prompt"] = "私密提示词"
    prediction["response"] = "私密模型响应"
    predictions_path.write_text(
        json.dumps(prediction, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    first = evaluate_audit_files(gold_path, predictions_path)
    second = evaluate_audit_files(gold_path, predictions_path)
    serialized = json.dumps(first, ensure_ascii=False)

    assert first["input_hashes"] == second["input_hashes"]
    assert set(first["input_hashes"]) == {"gold_sha256", "predictions_sha256"}
    assert "不应进入评测报告的合同正文" not in serialized
    assert "私密提示词" not in serialized
    assert "私密模型响应" not in serialized


def test_file_evaluation_parses_and_hashes_the_same_byte_snapshot(monkeypatch, tmp_path):
    gold_path = tmp_path / "gold.jsonl"
    predictions_path = tmp_path / "predictions.jsonl"
    gold_path.write_text(
        json.dumps(_gold_case(), ensure_ascii=False) + "\n", encoding="utf-8"
    )
    predictions_path.write_text(
        json.dumps(_prediction(), ensure_ascii=False) + "\n", encoding="utf-8"
    )
    original_bytes = gold_path.read_bytes()
    replacement = json.dumps(_gold_case("c-2"), ensure_ascii=False) + "\n"
    original_read_text = Path.read_text
    original_write_text = Path.write_text

    def replace_after_text_read(path, *args, **kwargs):
        text = original_read_text(path, *args, **kwargs)
        if path == gold_path:
            original_write_text(path, replacement, encoding="utf-8")
        return text

    monkeypatch.setattr(Path, "read_text", replace_after_text_read)

    report = evaluate_audit_files(gold_path, predictions_path)

    assert report["input_hashes"]["gold_sha256"] == hashlib.sha256(
        original_bytes
    ).hexdigest()


def test_file_evaluation_rejects_empty_or_non_object_jsonl(tmp_path):
    empty = tmp_path / "empty.jsonl"
    empty.write_text("", encoding="utf-8")
    predictions = tmp_path / "predictions.jsonl"
    predictions.write_text(json.dumps(_prediction()) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="不能为空"):
        evaluate_audit_files(empty, predictions)

    gold = tmp_path / "gold.jsonl"
    gold.write_text("[]\n", encoding="utf-8")
    with pytest.raises(ValueError, match="JSON 对象"):
        evaluate_audit_files(gold, predictions)
