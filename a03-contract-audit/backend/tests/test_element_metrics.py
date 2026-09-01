"""要素准确率必须基于人工金标准计算。"""
import pytest

from evaluation.elements import (
    evaluate_dataset,
    multivalue_metrics,
    scalar_accuracy,
    validate_gold_record,
)


def _valid_gold_record() -> dict:
    return {
        "case_id": "case-1",
        "file": "case-1.pdf",
        "contract_type": "采购合同",
        "document_kind": "pdf",
        "reviewers": ["reviewer-a", "reviewer-b"],
        "review_status": "agreed",
        "version": "v1",
        "gold": {
            "party_a": "甲公司",
            "party_b": "乙公司",
            "subject": "设备采购",
            "amount": "100万元",
            "duration": "12个月",
            "payment_terms": ["首付款", "验收款"],
        },
    }


def test_scalar_accuracy_uses_gold_labels():
    assert scalar_accuracy(["甲公司", "乙公司"], ["甲公司", "错误公司"]) == 0.5


def test_scalar_accuracy_normalizes_surrounding_whitespace():
    assert scalar_accuracy([" 甲公司\n"], ["甲公司"]) == 1.0


def test_empty_scalar_is_only_correct_when_gold_is_also_empty():
    assert scalar_accuracy([None, None], [None, "误报"]) == 0.5


def test_multivalue_metrics_count_missing_and_extra_values():
    metrics = multivalue_metrics(["首付款", "验收款"], ["首付款", "质保金"])

    assert metrics == {"precision": 0.5, "recall": 0.5, "f1": 0.5}


def test_gold_record_requires_frozen_audit_fields():
    record = _valid_gold_record()
    del record["reviewers"]

    with pytest.raises(ValueError, match="reviewers"):
        validate_gold_record(record)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda row: row.update(document_kind="jpg"), "document_kind"),
        (lambda row: row.update(reviewers=["reviewer-a"]), "reviewers"),
        (lambda row: row["gold"].update(payment_terms="首付款"), "payment_terms"),
    ],
)
def test_gold_record_enforces_json_schema(mutate, message):
    record = _valid_gold_record()
    mutate(record)

    with pytest.raises(ValueError, match=message):
        validate_gold_record(record)


def test_adjudicated_record_requires_adjudicator():
    record = _valid_gold_record()
    record["review_status"] = "adjudicated"

    with pytest.raises(ValueError, match="adjudicator"):
        validate_gold_record(record)


def test_evaluation_rejects_unknown_prediction_case_id():
    with pytest.raises(ValueError, match="unknown-case"):
        evaluate_dataset(
            [_valid_gold_record()],
            {
                "case-1": _valid_gold_record()["gold"],
                "unknown-case": _valid_gold_record()["gold"],
            },
        )


def test_evaluation_reports_macro_groups_and_error_cases():
    gold_records = [_valid_gold_record()]
    predictions = {
        "case-1": {
            "party_a": "甲公司",
            "party_b": "错误公司",
            "subject": "设备采购",
            "amount": "100万元",
            "duration": "12个月",
            "payment_terms": ["首付款", "质保金"],
        }
    }

    report = evaluate_dataset(gold_records, predictions)

    assert report["sample_count"] == 1
    assert report["overall"]["f1"] == pytest.approx(0.75)
    assert report["by_contract_type"]["采购合同"]["sample_count"] == 1
    assert report["by_document_kind"]["pdf"]["sample_count"] == 1
    assert {error["field"] for error in report["errors"]} == {"party_b", "payment_terms"}
    assert len(report["dataset_sha256"]) == 64
