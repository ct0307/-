"""RAG 检索金标评测：Recall@K、Precision@K、MRR 与 nDCG@K。"""
from __future__ import annotations

import math
from typing import Any, Mapping, Sequence


def evaluate_retrieval_dataset(
    gold_records: Sequence[Mapping[str, Any]],
    predictions: Mapping[str, Sequence[str]],
    *,
    k_values: Sequence[int] = (5, 20),
) -> dict[str, Any]:
    if not gold_records:
        raise ValueError("检索金标准不能为空")
    ks = tuple(dict.fromkeys(int(value) for value in k_values))
    if not ks or any(value < 1 for value in ks):
        raise ValueError("k_values 必须是正整数")

    gold: dict[str, tuple[str, ...]] = {}
    for index, record in enumerate(gold_records):
        case_id = str(record.get("case_id", "")).strip()
        relevant = _id_list(record.get("relevant_ids"), f"gold[{index}].relevant_ids")
        if not case_id:
            raise ValueError(f"gold[{index}] 缺少 case_id")
        if not relevant:
            raise ValueError(f"gold[{index}].relevant_ids 不能为空")
        if case_id in gold:
            raise ValueError(f"金标准 case_id 重复: {case_id}")
        gold[case_id] = relevant

    unknown = sorted(set(predictions) - set(gold))
    if unknown:
        raise ValueError(f"预测包含未知 case_id: {', '.join(unknown)}")

    cases: list[dict[str, Any]] = []
    missing = 0
    for case_id, relevant_ids in gold.items():
        if case_id not in predictions:
            missing += 1
        ranked_ids = _id_list(predictions.get(case_id, ()), f"predictions[{case_id}]")
        relevant = set(relevant_ids)
        metrics: dict[str, float] = {}
        for k in ks:
            top = ranked_ids[:k]
            hits = sum(item in relevant for item in top)
            metrics[f"recall@{k}"] = hits / len(relevant)
            metrics[f"precision@{k}"] = hits / k
            metrics[f"ndcg@{k}"] = _ndcg(top, relevant, k)
        first_rank = next(
            (rank for rank, item in enumerate(ranked_ids, start=1) if item in relevant),
            None,
        )
        metrics["mrr"] = 1 / first_rank if first_rank is not None else 0.0
        cases.append({
            "case_id": case_id,
            "relevant_count": len(relevant),
            "retrieved_count": len(ranked_ids),
            "metrics": metrics,
        })

    metric_names = [
        name
        for k in ks
        for name in (f"recall@{k}", f"precision@{k}", f"ndcg@{k}")
    ] + ["mrr"]
    overall = {
        name: sum(case["metrics"][name] for case in cases) / len(cases)
        for name in metric_names
    }
    return {
        "sample_count": len(cases),
        "missing_prediction_count": missing,
        "overall": overall,
        "cases": cases,
    }


def _id_list(value: Any, location: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ValueError(f"{location} 必须是 ID 数组")
    result = tuple(str(item).strip() for item in value)
    if any(not item for item in result):
        raise ValueError(f"{location} 不能包含空 ID")
    if len(set(result)) != len(result):
        raise ValueError(f"{location} 包含重复 ID")
    return result


def _ndcg(ranked_ids: Sequence[str], relevant: set[str], k: int) -> float:
    dcg = sum(
        1 / math.log2(rank + 1)
        for rank, item in enumerate(ranked_ids[:k], start=1)
        if item in relevant
    )
    ideal_hits = min(k, len(relevant))
    ideal = sum(1 / math.log2(rank + 1) for rank in range(1, ideal_hits + 1))
    return dcg / ideal if ideal else 0.0
