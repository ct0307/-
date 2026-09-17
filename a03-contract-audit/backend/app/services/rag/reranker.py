"""默认关闭、仅从本地缓存加载的 Cross-Encoder 精排适配器。"""
from __future__ import annotations

from functools import lru_cache
from typing import Protocol, Sequence

from app.core.config import settings


class _CrossEncoderModel(Protocol):
    def predict(self, pairs: list[tuple[str, str]]) -> Sequence[float]: ...


class LocalCrossEncoderReranker:
    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        self._model: _CrossEncoderModel | None = None

    def score(self, query: str, documents: list[str]) -> list[float]:
        if not documents:
            return []
        if self._model is None:
            self._model = _load_cross_encoder(self.model_name)
        values = self._model.predict([(query, document) for document in documents])
        return [float(value) for value in values]


def get_reranker() -> LocalCrossEncoderReranker | None:
    backend = settings.RERANK_BACKEND
    if backend == "disabled":
        return None
    if backend == "local":
        return _local_reranker(settings.RERANK_MODEL)
    raise ValueError(f"未知 RERANK_BACKEND: {backend}")


@lru_cache(maxsize=4)
def _local_reranker(model_name: str) -> LocalCrossEncoderReranker:
    return LocalCrossEncoderReranker(model_name)


def _load_cross_encoder(model_name: str) -> _CrossEncoderModel:
    try:
        from sentence_transformers import CrossEncoder
    except ImportError as exc:
        raise RuntimeError("Cross-Encoder 运行依赖不可用") from exc
    try:
        return CrossEncoder(model_name, local_files_only=True)
    except Exception as exc:
        raise RuntimeError("Cross-Encoder 本地模型不可用") from exc
