import json
from unittest.mock import patch

import pytest

from app.llm.base import LLMError
from app.services.rag import retriever


class FakeEmbeddingAdapter:
    def __init__(self, vectors):
        self.vectors = vectors
        self.inputs = []

    def embed(self, texts):
        self.inputs.append(list(texts))
        return self.vectors


def _legal_chunk(**overrides):
    chunk = {
        "category": "law",
        "source": "中华人民共和国民法典",
        "content": "第五百一十一条 第一款正文。",
        "retrieval_text": "中华人民共和国民法典 第三编 合同 第五百一十一条 第一款正文。",
        "article_number": "第五百一十一条",
        "chunk_index": 0,
        "chunk_count": 1,
        "chunk_schema_version": "legal-v1",
        "scope_mode": "global",
    }
    return {**chunk, **overrides}


def test_embedding_signature_is_stable_and_version_sensitive():
    base = retriever.embedding_signature(
        backend="local",
        model="bge-test",
        dimension=2,
        normalization="l2",
        chunk_schema_version="legal-v1",
    )

    assert base == retriever.embedding_signature(
        backend="local",
        model="bge-test",
        dimension=2,
        normalization="l2",
        chunk_schema_version="legal-v1",
    )
    assert base != retriever.embedding_signature(
        backend="local",
        model="bge-test",
        dimension=2,
        normalization="l2",
        chunk_schema_version="legal-v2",
    )


def test_legal_embedding_uses_retrieval_text_and_records_signature():
    adapter = FakeEmbeddingAdapter([[1.0, 0.0]])
    with (
        patch.object(retriever, "get_embedding_adapter", return_value=adapter),
        patch.object(retriever.settings, "EMBED_DIM", 2),
    ):
        row = retriever.prepare_documents([_legal_chunk()])[0]

    assert adapter.inputs == [[_legal_chunk()["retrieval_text"]]]
    assert row.retrieval_text == _legal_chunk()["retrieval_text"]
    assert row.embedding_signature
    assert row.chunk_schema_version == "legal-v1"
    assert row.chunk_index == 0
    assert row.chunk_count == 1


@pytest.mark.parametrize(
    "vectors",
    [[], [[float("nan"), 0.0]], [[float("inf"), 0.0]], [[1.0]], [[1.0, 0.0, 0.0]]],
)
def test_legal_embedding_rejects_invalid_count_values_and_dimension(vectors):
    with (
        patch.object(
            retriever, "get_embedding_adapter", return_value=FakeEmbeddingAdapter(vectors)
        ),
        patch.object(retriever.settings, "EMBED_DIM", 2),
    ):
        with pytest.raises(LLMError):
            retriever.prepare_documents([_legal_chunk()])


def test_matching_retrieval_hash_and_signature_reuses_embedding():
    first_adapter = FakeEmbeddingAdapter([[0.6, 0.8]])
    with (
        patch.object(retriever, "get_embedding_adapter", return_value=first_adapter),
        patch.object(retriever.settings, "EMBED_DIM", 2),
    ):
        first = retriever.prepare_documents([_legal_chunk()])[0]
    cache = {
        (first.content_hash, first.embedding_signature): json.loads(first.embedding)
    }
    unused_adapter = FakeEmbeddingAdapter([])

    with (
        patch.object(retriever, "get_embedding_adapter", return_value=unused_adapter),
        patch.object(retriever.settings, "EMBED_DIM", 2),
    ):
        reused = retriever.prepare_documents([_legal_chunk()], embedding_cache=cache)[0]

    assert unused_adapter.inputs == []
    assert reused.embedding == first.embedding


def test_changed_retrieval_text_rebuilds_embedding():
    adapter = FakeEmbeddingAdapter([[0.0, 1.0]])
    with (
        patch.object(retriever, "get_embedding_adapter", return_value=adapter),
        patch.object(retriever.settings, "EMBED_DIM", 2),
    ):
        row = retriever.prepare_documents(
            [_legal_chunk(retrieval_text="修改后的检索文本")],
            embedding_cache={("unrelated", "signature"): [1.0, 0.0]},
        )[0]

    assert adapter.inputs == [["修改后的检索文本"]]
    assert json.loads(row.embedding) == [0.0, 1.0]
