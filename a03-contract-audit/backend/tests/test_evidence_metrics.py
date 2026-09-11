"""支持关系金标评测的输入约束与指标。"""

import pytest

from evaluation.evidence_metrics import evaluate_evidence_dataset, validate_evidence_gold_record


def _gold() -> dict:
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
            "payment_terms": ["首付款"],
        },
        "evidence": [
            {"risk_key": "risk-1", "support_relation_status": "supported"},
            {"risk_key": "risk-2", "support_relation_status": "unclear"},
        ],
    }


def test_evidence_gold_requires_reviewed_risk_statuses():
    record = _gold()
    validate_evidence_gold_record(record)

    record["evidence"][0]["support_relation_status"] = "guess"
    with pytest.raises(ValueError, match="support_relation_status"):
        validate_evidence_gold_record(record)


def test_evidence_metrics_report_macro_f1_and_missing_predictions():
    result = evaluate_evidence_dataset(
        [_gold()],
        {
            "case-1": {
                "evidence": [
                    {"risk_key": "risk-1", "support_relation_status": "supported"}
                ]
            }
        },
    )

    assert result["sample_count"] == 1
    assert result["overall"]["macro_f1"] == pytest.approx(1 / 3)
    assert result["overall"]["accuracy"] == pytest.approx(0.5)
    assert result["cases"][0]["missing_prediction_count"] == 1


def test_evidence_metrics_reject_unknown_case_or_risk_key():
    with pytest.raises(ValueError, match="未知预测 case_id"):
        evaluate_evidence_dataset([_gold()], {"unknown": {"evidence": []}})

    with pytest.raises(ValueError, match="未知 risk_key"):
        evaluate_evidence_dataset(
            [_gold()],
            {
                "case-1": {
                    "evidence": [
                        {"risk_key": "risk-x", "support_relation_status": "supported"}
                    ]
                }
            },
        )
