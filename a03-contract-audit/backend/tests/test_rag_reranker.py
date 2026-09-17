"""可选本地 Cross-Encoder 精排适配器。"""

from app.services.rag import reranker, retriever


def test_disabled_reranker_returns_none(monkeypatch):
    monkeypatch.setattr(reranker.settings, "RERANK_BACKEND", "disabled")

    assert reranker.get_reranker() is None


def test_local_reranker_scores_in_one_batch(monkeypatch):
    class FakeCrossEncoder:
        def __init__(self):
            self.calls = []

        def predict(self, pairs):
            self.calls.append(pairs)
            return [0.2, 0.9]

    fake = FakeCrossEncoder()
    monkeypatch.setattr(reranker, "_load_cross_encoder", lambda _name: fake)
    scorer = reranker.LocalCrossEncoderReranker("test-model")

    assert scorer.score("查询", ["甲", "乙"]) == [0.2, 0.9]
    assert fake.calls == [[("查询", "甲"), ("查询", "乙")]]


def test_retrieval_reranks_only_configured_candidate_prefix(monkeypatch):
    class FakeReranker:
        def __init__(self):
            self.calls = []

        def score(self, query, documents):
            self.calls.append((query, documents))
            return [float(index) for index in range(len(documents))]

    fake = FakeReranker()
    candidates = [
        {
            "chunk_id": index,
            "content": f"候选{index}",
            "matched_content": f"候选{index}",
            "score": 1.0 / index,
        }
        for index in range(1, 7)
    ]
    monkeypatch.setattr(retriever, "get_reranker", lambda: fake)
    monkeypatch.setattr(retriever.settings, "RERANK_CANDIDATE_K", 5)

    ranked = retriever._rerank_candidates(
        "查询",
        candidates,
        route_ranks={},
        expanded_query="查询 扩展",
    )

    assert fake.calls == [(
        "查询",
        ["候选1", "候选2", "候选3", "候选4", "候选5"],
    )]
    assert [item["chunk_id"] for item in ranked[:5]] == [5, 4, 3, 2, 1]
    assert ranked[5]["chunk_id"] == 6
    assert ranked[5]["retrieval_trace"]["rerank_mode"] == "deterministic_evidence_v1"


def test_reranker_failure_preserves_rrf_order_and_records_error(monkeypatch):
    class FailingReranker:
        def score(self, _query, _documents):
            raise RuntimeError("本地模型不可用")

    candidates = [
        {"chunk_id": 1, "content": "候选甲", "score": 0.2},
        {"chunk_id": 2, "content": "候选乙", "score": 0.1},
    ]
    monkeypatch.setattr(retriever, "get_reranker", lambda: FailingReranker())

    ranked = retriever._rerank_candidates(
        "查询",
        candidates,
        route_ranks={},
        expanded_query="查询",
    )

    assert [item["chunk_id"] for item in ranked] == [1, 2]
    assert all(
        item["retrieval_trace"]["rerank_mode"] == "deterministic_evidence_v1"
        for item in ranked
    )
    assert all(
        item["retrieval_trace"]["rerank_error_code"] == "RERANK_SCORING_FAILED"
        for item in ranked
    )
