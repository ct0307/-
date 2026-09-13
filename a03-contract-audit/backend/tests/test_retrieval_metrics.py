import pytest


def test_retrieval_metrics_report_recall_precision_mrr_and_ndcg():
    from evaluation.retrieval_metrics import evaluate_retrieval_dataset

    gold = [
        {"case_id": "q1", "relevant_ids": ["A", "B"]},
        {"case_id": "q2", "relevant_ids": ["C"]},
    ]
    predictions = {
        "q1": ["X", "A", "B"],
        "q2": ["C", "Y"],
    }

    report = evaluate_retrieval_dataset(gold, predictions, k_values=(1, 2))

    assert report["sample_count"] == 2
    assert report["overall"]["recall@1"] == pytest.approx(0.5)
    assert report["overall"]["recall@2"] == pytest.approx(0.75)
    assert report["overall"]["precision@2"] == pytest.approx(0.5)
    assert report["overall"]["mrr"] == pytest.approx(0.75)
    assert 0 < report["overall"]["ndcg@2"] <= 1


def test_retrieval_metrics_count_missing_prediction_as_zero():
    from evaluation.retrieval_metrics import evaluate_retrieval_dataset

    report = evaluate_retrieval_dataset(
        [{"case_id": "q1", "relevant_ids": ["A"]}],
        {},
        k_values=(5,),
    )

    assert report["missing_prediction_count"] == 1
    assert report["overall"] == {
        "recall@5": 0.0,
        "precision@5": 0.0,
        "ndcg@5": 0.0,
        "mrr": 0.0,
    }


@pytest.mark.parametrize(
    ("gold", "predictions", "message"),
    [
        ([{"case_id": "q1", "relevant_ids": []}], {}, "relevant_ids"),
        ([{"case_id": "q1", "relevant_ids": ["A", "A"]}], {}, "重复"),
        ([{"case_id": "q1", "relevant_ids": ["A"]}], {"q1": ["A", "A"]}, "重复"),
        ([{"case_id": "q1", "relevant_ids": ["A"]}], {"unknown": ["A"]}, "未知"),
    ],
)
def test_retrieval_metrics_reject_ambiguous_gold_or_predictions(gold, predictions, message):
    from evaluation.retrieval_metrics import evaluate_retrieval_dataset

    with pytest.raises(ValueError, match=message):
        evaluate_retrieval_dataset(gold, predictions)
