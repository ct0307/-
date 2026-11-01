"""执行结构化证据查询计划并生成可重放检索轨迹。"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Callable, Protocol

from app.services.rag.query_planner import EvidenceQuery, EvidenceQueryPlan


class SupportResult(Protocol):
    status: str


Search = Callable[[EvidenceQuery], list[dict]]
Validate = Callable[[list[dict]], SupportResult]
Rewrite = Callable[[EvidenceQuery, str], EvidenceQuery | None]


@dataclass(frozen=True)
class RetrievalAttempt:
    query_kind: str
    query: str
    rewrite: int
    result_ids: tuple[str, ...]
    retrieval_mode: str
    routes: tuple[dict, ...]
    rerank_mode: str
    applicability_status: str
    support_status: str = "unvalidated"

    def as_dict(self, *, attempt: int) -> dict:
        """保留旧轨迹键，同时追加结构化查询元数据。"""
        return {
            "attempt": attempt,
            "query": self.query,
            "support_status": self.support_status,
            "source_ids": list(self.result_ids),
            "query_kind": self.query_kind,
            "rewrite": self.rewrite,
            "retrieval_mode": self.retrieval_mode,
            "routes": list(self.routes),
            "rerank_mode": self.rerank_mode,
            "applicability_status": self.applicability_status,
        }


@dataclass(frozen=True)
class QueryPlanResult:
    sources: tuple[dict, ...]
    attempts: tuple[RetrievalAttempt, ...]
    support_status: str
    validation: SupportResult


def execute_query_plan(
    plan: EvidenceQueryPlan,
    *,
    search: Search,
    validate: Validate,
    rewrite: Rewrite,
) -> QueryPlanResult:
    """执行首轮多路查询，并在整体不支持时最多受控改写一次。"""
    attempts: list[RetrievalAttempt] = []
    merged: list[dict] = []
    seen: set[tuple[str, str]] = set()

    def run_round(queries: tuple[EvidenceQuery, ...], rewrite_number: int) -> SupportResult:
        pending: list[RetrievalAttempt] = []
        for query in queries:
            results = list(search(query) or [])
            for item in results:
                key = _deduplication_key(item)
                if key in seen:
                    continue
                seen.add(key)
                merged.append(item)
            pending.append(_attempt_from_results(query, rewrite_number, results))
        validation = validate(merged)
        attempts.extend(
            replace(attempt, support_status=validation.status)
            for attempt in pending
        )
        return validation

    validation = run_round(plan.queries, 0)
    if validation.status == "supported" or plan.max_rewrites < 1:
        return QueryPlanResult(
            tuple(merged), tuple(attempts), validation.status, validation
        )

    reason_code = _validation_reason_code(validation)
    rewritten = tuple(
        candidate
        for query in plan.queries
        if (candidate := rewrite(query, reason_code)) is not None
        and candidate.text != query.text
    )
    if rewritten:
        validation = run_round(rewritten, 1)
    return QueryPlanResult(
        tuple(merged), tuple(attempts), validation.status, validation
    )


def _attempt_from_results(
    query: EvidenceQuery,
    rewrite_number: int,
    results: list[dict],
) -> RetrievalAttempt:
    traces = [
        item.get("retrieval_trace")
        if isinstance(item.get("retrieval_trace"), dict) else {}
        for item in results
    ]
    routes = tuple(
        dict(trace["routes"])
        for trace in traces
        if isinstance(trace.get("routes"), dict)
    )
    return RetrievalAttempt(
        query_kind=query.kind,
        query=query.text,
        rewrite=rewrite_number,
        result_ids=tuple(_result_id(item) for item in results),
        retrieval_mode=_aggregate(
            [str(item.get("retrieval_mode") or "none") for item in results]
        ),
        routes=routes,
        rerank_mode=_aggregate(
            [str(trace.get("rerank_mode") or "none") for trace in traces]
        ),
        applicability_status=_aggregate([
            str(item.get("applicability_status") or "applicable")
            for item in results
        ]),
    )


def _deduplication_key(item: dict) -> tuple[str, str]:
    article_id = item.get("legal_article_id")
    if article_id is not None:
        return "legal_article", str(article_id)
    chunk_id = item.get("chunk_id")
    if chunk_id is not None:
        return "chunk", str(chunk_id)
    return "legacy", f"{item.get('source', '')}\0{item.get('content', '')}"


def _result_id(item: dict) -> str:
    chunk_id = item.get("chunk_id")
    if chunk_id is not None:
        return f"KC-{chunk_id}"
    article_id = item.get("legal_article_id")
    if article_id is not None:
        return f"LA-{article_id}"
    return str(item.get("source") or "unknown")


def _aggregate(values: list[str]) -> str:
    unique = tuple(dict.fromkeys(value for value in values if value))
    if not unique:
        return "none"
    if len(unique) == 1:
        return unique[0]
    return "mixed"


def _validation_reason_code(validation: SupportResult) -> str:
    reason_code = getattr(validation, "reason_code", None)
    if isinstance(reason_code, str) and reason_code:
        return reason_code
    if validation.status == "supported":
        return "EVIDENCE_SUPPORTED"
    return "INSUFFICIENT_SUPPORT"
