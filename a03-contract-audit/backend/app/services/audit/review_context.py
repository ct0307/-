"""为模型提供确定的阅读范围；不将目录或引用线索当作证据结论。"""
from __future__ import annotations

import json
import re

from app.services.rag.contract_structure import build_contract_chunks


class ReviewContext:
    def __init__(self, contract_text: str):
        self._characters = len(contract_text)
        self._normalized = re.sub(r'\s+', '', contract_text)
        headings = [chunk.text.splitlines()[0][:80] for chunk in build_contract_chunks(contract_text)]
        self._outline = headings[:60]
        self._outline_truncated = len(headings) > 60
        clues = [line.strip()[:180] for line in contract_text.splitlines()
                 if re.search(r'主协议|主合同|框架协议', line)]
        self._clues = list(dict.fromkeys(clues))[:8]
        self._clues_truncated = len(dict.fromkeys(clues)) > 8

    def render(self, window_text: str) -> str:
        scope = dict(
            window_covers_full_text=bool(self._normalized) and re.sub(r'\s+', '', window_text) == self._normalized,
            whole_contract_characters=self._characters,
            window_characters=len(window_text),
            whole_contract_outline=self._outline,
            outline_truncated=self._outline_truncated,
            referenced_document_clues=self._clues,
            reference_clues_truncated=self._clues_truncated,
        )
        # 所有原文均编码为JSON值，避免正文中的标签改变范围数据的结构。
        payload = json.dumps(scope, ensure_ascii=False).replace('<', '\\u003c').replace('>', '\\u003e')
        return f'<review_scope>\n{payload}\n</review_scope>\n'
