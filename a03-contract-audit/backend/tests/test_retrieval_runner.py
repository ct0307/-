import pytest
from evaluation.retrieval_runner import predict
from evaluation.retrieval_metrics import evaluate_retrieval_dataset


def test_predictions_preserve_failed_queries_and_use_source_identity():
    def retrieve(query, **kwargs):
        assert kwargs["top_k"] == 5
        if query == "失败":
            raise RuntimeError("不应写入产物的敏感正文")
        return [{"source_id": "civil-code", "article_number": "第十条", "retrieval_mode": "exact"}]
    gold = [{"case_id": "a", "query": "民法典第十条", "relevant_ids": ["civil-code:第十条"]},
            {"case_id": "b", "query": "失败", "relevant_ids": ["chunk:2"]}]
    rows = predict(gold, retriever=retrieve, top_k=5)
    assert rows[1]["ranked_ids"] == []
    assert rows[1]["error_code"] == "RuntimeError"
    assert "敏感" not in repr(rows)
    metrics = evaluate_retrieval_dataset(gold, {row["case_id"]: row["ranked_ids"] for row in rows}, k_values=(5,))
    assert metrics["overall"]["recall@5"] == 0.5


def test_repeated_case_ids_rejected_before_any_retrieval():
    with pytest.raises(ValueError, match="唯一"):
        predict([{"case_id": "x", "query": "一"}, {"case_id": "x", "query": "二"}],
                retriever=lambda *a, **k: pytest.fail("无效输入不能开始检索"), top_k=5)
