"""风险级法规证据检索与绑定。"""
from collections.abc import Callable
from typing import Any

from app.core.logging import get_logger
from app.services.rag.retriever import retrieve

log = get_logger("audit.evidence")

SearchFn = Callable[..., list[dict[str, Any]]]
_NO_EVIDENCE = "未检索到可靠法规或规则依据，必须由人工复核后确认。"


def build_evidence_query(category: str, original_text: str) -> str:
    """用风险类别和有限长度原文构造稳定、可审计的检索词。"""
    clean_category = " ".join(str(category or "").split())
    clean_original = " ".join(str(original_text or "").split())[:240]
    return " ".join(part for part in (clean_category, clean_original) if part)


def bind_risk_evidence(
    risk: dict[str, Any],
    *,
    search: SearchFn | None = None,
    top_k: int = 3,
) -> dict[str, Any]:
    """为单条风险独立检索并覆盖正式依据，检索失败时强制人工复核。"""
    search_fn = search or retrieve
    query = build_evidence_query(
        str(risk.get("category", "")),
        str(risk.get("original_text", "")),
    )
    try:
        raw_sources = search_fn(query, top_k=top_k) if query else []
    except Exception as exc:
        log.warning("audit.evidence_search_failed", error=str(exc)[:120])
        raw_sources = []

    sources: list[dict[str, Any]] = []
    for item in raw_sources:
        content = str(item.get("content", "")).strip()
        source = str(item.get("source", "")).strip()
        if not content or not source:
            continue
        sources.append({
            "content": content,
            "source": source,
            "score": item.get("score", 0),
        })

    risk["rag_sources"] = sources
    risk["basis"] = (
        "；".join(f"{item['content']}（依据：{item['source']}）" for item in sources)
        if sources
        else _NO_EVIDENCE
    )
    return risk
