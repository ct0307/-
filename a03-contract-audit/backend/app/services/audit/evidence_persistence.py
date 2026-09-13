"""合同条款、来源锚点与风险定位证据的持久化辅助。"""

from __future__ import annotations

from dataclasses import asdict
import json
import re
from collections.abc import Sequence

from sqlalchemy.orm import Session

from app.models.models import ContractClause
from app.services.parser.extractor import DocumentParseResult
from app.services.rag.contract_structure import build_contract_chunks


def replace_contract_clauses(
    db: Session,
    *,
    contract_id: int,
    audit_generation: int,
    parsed: DocumentParseResult,
) -> list[ContractClause]:
    """用本次解析结果替换合同当前条款，调用方负责提交事务。"""
    db.query(ContractClause).filter(
        ContractClause.contract_id == contract_id
    ).delete(synchronize_session=False)

    records = [
        ContractClause(
            contract_id=contract_id,
            audit_generation=audit_generation,
            chunk_id=chunk.chunk_id,
            clause_id=chunk.clause_id,
            clause_path_json=json.dumps(list(chunk.clause_path), ensure_ascii=False),
            content=chunk.text,
            block_type=chunk.block_type,
            char_start=chunk.anchor.char_start,
            char_end=chunk.anchor.char_end,
            parent_chunk_id=chunk.parent_chunk_id,
            previous_chunk_id=chunk.previous_chunk_id,
            next_chunk_id=chunk.next_chunk_id,
            source_anchors_json=json.dumps(
                [asdict(anchor) for anchor in chunk.source_anchors],
                ensure_ascii=False,
            ),
        )
        for chunk in build_contract_chunks(parsed.text, blocks=parsed.blocks)
    ]
    db.add_all(records)
    db.flush()
    return records


def build_contract_evidence(
    risk: dict,
    clauses: Sequence[ContractClause],
    *,
    max_matches: int = 3,
) -> list[dict]:
    """把风险引文绑定到条款；降级提示不会伪装成精确匹配。"""
    quote = _normalize_text(risk.get("original_text", ""))
    hinted_ids = {
        str(value).strip()
        for value in risk.get("source_clause_ids", [])
        if str(value).strip()
    }
    ordered = sorted(
        clauses,
        key=lambda clause: (
            clause.clause_id not in hinted_ids,
            clause.char_start is None,
            clause.char_start or 0,
            clause.chunk_id,
        ),
    )

    if quote and "全文未检出" not in quote:
        exact = [
            clause
            for clause in ordered
            if quote in _normalize_text(clause.content)
        ]
        if exact:
            return [
                _evidence_payload(clause, match_type="exact_quote", score=1.0)
                for clause in exact[:max_matches]
            ]

    hinted = [clause for clause in ordered if clause.clause_id in hinted_ids]
    return [
        _evidence_payload(clause, match_type="clause_hint", score=0.55)
        for clause in hinted[:max_matches]
    ]


def _evidence_payload(
    clause: ContractClause,
    *,
    match_type: str,
    score: float,
) -> dict:
    return {
        "chunk_id": clause.chunk_id,
        "clause_id": clause.clause_id,
        "clause_path": _json_list(clause.clause_path_json),
        "char_start": clause.char_start,
        "char_end": clause.char_end,
        "anchors": _json_list(clause.source_anchors_json),
        "match_type": match_type,
        "score": score,
    }


def _json_list(raw: str | None) -> list:
    try:
        value = json.loads(raw or "[]")
    except (TypeError, ValueError):
        return []
    return value if isinstance(value, list) else []


def _normalize_text(value: object) -> str:
    return re.sub(r"\s+", "", str(value or ""))
