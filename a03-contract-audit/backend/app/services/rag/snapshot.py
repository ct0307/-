"""按知识库修订号复用的不可变检索快照。"""
from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from typing import Callable, Hashable

import numpy as np


@dataclass(frozen=True)
class RetrievalSnapshot:
    revision: int
    docs: tuple[tuple, ...]
    bm25: object | None
    bm25_doc_ids: tuple[int, ...]
    vector_doc_ids: tuple[int, ...]
    vector_matrix: np.ndarray


class SnapshotStore:
    """保证同一快照身份只构建一次，完整构建后再替换当前值。"""

    def __init__(self) -> None:
        self._lock = Lock()
        self._identity: Hashable | None = None
        self._current: RetrievalSnapshot | None = None

    def get(
        self,
        identity: Hashable,
        builder: Callable[[], RetrievalSnapshot],
    ) -> RetrievalSnapshot:
        current = self._current
        if current is not None and self._identity == identity:
            return current
        with self._lock:
            current = self._current
            if current is not None and self._identity == identity:
                return current
            built = builder()
            self._current = built
            self._identity = identity
            return built

    def clear(self) -> None:
        with self._lock:
            self._current = None
            self._identity = None
