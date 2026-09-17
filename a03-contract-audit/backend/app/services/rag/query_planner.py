"""为结构化 Claim 生成可序列化、可审计的证据查询计划。"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Literal

from app.services.audit.claims import AuditClaim


QUERY_PLAN_VERSION = "query-plan-v1"

QueryKind = Literal[
    "exact_reference",
    "legal_issue",
    "fact_pattern",
    "applicability",
    "absence_requirement",
]

_ARTICLE_REFERENCE_RE = re.compile(
    r"(?:《[^》]{2,80}》)?第[一二三四五六七八九十百千万零〇两\d]+条"
    r"(?:之[一二三四五六七八九十\d]+)?"
)

@dataclass(frozen=True)
class EvidenceQuery:
    kind: QueryKind
    text: str
    contract_type: str
    dimensions: tuple[str, ...]


@dataclass(frozen=True)
class EvidenceQueryPlan:
    claim_id: str
    queries: tuple[EvidenceQuery, ...]
    max_rewrites: int = 1
    version: str = QUERY_PLAN_VERSION


def plan_claim(
    claim: AuditClaim,
    *,
    contract_type: str = "",
) -> EvidenceQueryPlan:
    """根据 Claim 已声明事实选择检索路线，不补写未知事实。"""
    dimensions = (claim.dimension,)
    context = _join_nonempty(
        claim.category,
        claim.subject,
        claim.action,
        claim.condition,
        claim.consequence,
        claim.quote,
    )
    references = tuple(dict.fromkeys(_ARTICLE_REFERENCE_RE.findall(context)))
    normal_candidates: tuple[tuple[QueryKind, str], ...] = (
        (
            "legal_issue",
            _join_nonempty(contract_type, claim.category, "法律规则"),
        ),
        (
            "fact_pattern",
            _join_nonempty(
                contract_type,
                claim.subject,
                claim.action,
                claim.condition,
                claim.consequence,
                claim.quote,
            ),
        ),
        (
            "applicability",
            _join_nonempty(contract_type, claim.category, "适用范围 生效时间"),
        ),
    )
    if references:
        candidates = (("exact_reference", " ".join(references)),)
    elif claim.missing_information:
        candidates = ((
            "absence_requirement",
            _join_nonempty(
                contract_type,
                claim.category,
                *claim.missing_information,
                "法定要求",
            ),
        ),)
    else:
        candidates = normal_candidates

    queries: list[EvidenceQuery] = []
    seen: set[str] = set()
    for kind, text in candidates:
        normalized = " ".join(text.split())
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        queries.append(EvidenceQuery(
            kind=kind,
            text=normalized,
            contract_type=contract_type.strip(),
            dimensions=dimensions,
        ))
    return EvidenceQueryPlan(claim_id=claim.claim_id, queries=tuple(queries))


def _join_nonempty(*values: object) -> str:
    return " ".join(
        str(value).strip()
        for value in values
        if str(value).strip()
    )
