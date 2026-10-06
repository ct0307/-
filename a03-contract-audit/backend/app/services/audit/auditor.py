"""合规审查：核心业务，多智能体独立首审与交叉复核编排。

对应前端"双 Agent 协作"页：法务、财务独立首审，随后结构化交接、交叉验证和风险分级。

  法务独立首审 → 财务独立首审 → 白名单 Claim 交接
  → 交叉验证产出冲突项 → 每条风险分级归档（green/yellow/red）

每条风险包含（企业责任边界要求）：
  - 归属 agent（legal/finance）
  - 原文引用（original_text）
  - 依据来源（basis，来自 RAG 检索的法规/规则）
  - 风险等级（level: high/medium/low）
  - 证据状态（evidence_status）与人工复核要求
  - 建议修改（suggestion）
  - 人工干预档位（tier: green/yellow/red）

每个 Agent 通过窗口审查执行器调用模型；局部失败产生结构化问题，保留已验证结果。
所有结论统一标注"仅供参考，以人工复核为准"。
"""
import hashlib
import re
import json
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Callable

from app.core.config import settings
from app.core.logging import get_logger
from app.llm.factory import get_llm_adapter
from app.services.audit.workflow import AuditBudget, BudgetAdapter, directed_review, group_risks, runtime_identity
from app.services.audit.evidence_validation import (
    SUPPORT_VALIDATOR_VERSION,
    verify_support,
    validate_support_relation,
)
from app.services.audit.decision import apply_risk_decision, decide_risk
from app.services.audit.contract_logic import (
    analyze_payment_schedule,
    build_logic_cross_checks,
    candidate_dimensions,
    validate_candidate_facts,
)
from app.services.audit.deterministic_checks import find_deterministic_findings
from app.services.audit.agent_profiles import (
    AGENT_ORDER as _AGENT_ORDER,
    DIMENSION_TOPICS as _DIM_TOPICS,
    ROLE_DIMENSIONS as _ROLE_DIMENSIONS,
    AgentRole,
    agent_profile,
)
from app.services.audit.claims import AuditClaim, normalize_finding
from app.services.audit.collaboration import build_review_handoff, first_pass
from app.services.audit.prompts.review import (
    build_discovery_system_prompt,
    build_enrichment_system_prompt,
    build_review_system_prompt,
)
from app.services.audit.protocol import AgentReviewResult, ReviewIssue, RiskFinding
from app.services.audit.progress import ProgressCallback
from app.services.audit.review_pipeline import (
    BufferedWindowCheckpoint,
    BufferedWindowExecution,
    NullWindowCheckpoint,
    ReviewWindow,
    WindowReviewer,
    WindowReviewRequest,
    enrichment_candidate_id,
)
from app.services.audit.secondary_review import (
    SecondaryReviewer,
    SqlAlchemySecondaryCallRecorder,
    apply_secondary_decisions,
    conflict_claim_ids,
)
from app.services.audit.window_repository import SqlAlchemyWindowCheckpoint
from app.services.rag.contract_structure import build_contract_windows
from app.services.rag.query_executor import execute_query_plan
from app.services.rag.query_planner import plan_claim, rewrite_evidence_query
from app.services.rag.retriever import retrieve

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

log = get_logger("audit")

DISCLAIMER = "本结论由系统自动生成，仅供参考，以人工复核为准。"
NO_RELIABLE_BASIS = "无可靠检索依据，请人工复核"

_VALID_LEVELS = {"high", "medium", "low"}
_VALID_TIERS = {"green", "yellow", "red"}

# 红档敏感类别关键词：命中即强制升到红档（需三员会审），与前端分档口径一致。
_RED_KEYWORDS = ("关联交易", "关联方", "重大赔偿", "税法争议", "舞弊", "主体缺失", "收款账户")

@dataclass(frozen=True)
class AgentAuditResult:
    risks: list[dict]
    issues: list[ReviewIssue]
    planned: int
    completed: int


def audit_contract(
    elements: dict,
    contract_text: str,
    db: "Session | None" = None,
    contract_id: int | None = None,
    dimensions: list[str] | None = None,
    contract_type: str = "",
    audit_job_id: int | None = None,
    audit_generation: int = 0,
    deadline: float | None = None,
    clock: Callable[[], float] = time.monotonic,
    progress_callback: ProgressCallback | None = None,
    legal_as_of: date | None = None,
) -> dict:
    """多智能体主从协同审查。dimensions 为空/None 时全量审查。"""
    all_risks: list[dict] = []
    all_issues: list[ReviewIssue] = []
    planned = completed = 0
    canonical_dimensions = _canonical_dimensions(dimensions)
    _dimension_instruction(canonical_dimensions)
    from app.services.rag.revision import current_knowledge_revision
    knowledge_revision = current_knowledge_revision(db) if db is not None else 0
    identity = runtime_identity(contract_text, knowledge_revision=knowledge_revision)
    budget = AuditBudget(max_calls=settings.AUDIT_MAX_MODEL_CALLS, max_tokens=settings.AUDIT_MAX_TOKEN_BUDGET)
    adapter_factory = lambda: BudgetAdapter(get_llm_adapter(), budget)
    payment_schedule = analyze_payment_schedule(contract_text)
    shared_context: dict = {
        "elements": elements,
        "payment_schedule": {
            "status": payment_schedule.status,
            "total_percentage": (
                str(payment_schedule.total_percentage)
                if payment_schedule.total_percentage is not None else None
            ),
            "clause_ids": list(payment_schedule.clause_ids),
            "calculation": payment_schedule.calculation,
        },
    }
    timings = {
        "legal_agent_ms": 0,
        "finance_agent_ms": 0,
        "grounding_ms": 0,
    }

    active_roles = [
        role
        for role in _AGENT_ORDER
        if not canonical_dimensions
        or set(canonical_dimensions).intersection(_ROLE_DIMENSIONS[role])
    ]
    top_level_windows = build_contract_windows(contract_text, max_chars=8000)
    planned_units = len(active_roles) * len(top_level_windows)
    completed_units = 0

    def report_window_complete() -> None:
        nonlocal completed_units
        completed_units += 1
        if progress_callback is not None and planned_units:
            progress_callback(
                15 + (60 * completed_units // planned_units),
                "reviewing",
            )

    for role in _AGENT_ORDER:
        if role not in active_roles:
            log.info("audit.agent_skipped", agent=role, dimensions=canonical_dimensions)

    def run_first_pass(role: AgentRole) -> AgentAuditResult:
        return _agent_audit(
            role, elements, contract_text, shared_context,
            db=db, contract_id=contract_id,
            dimensions=canonical_dimensions,
            contract_type=contract_type,
            timings=timings,
            audit_job_id=audit_job_id,
            audit_generation=audit_generation,
            deadline=deadline,
            clock=clock,
            window_completed_callback=report_window_complete,
            legal_as_of=legal_as_of,
            adapter_factory=adapter_factory,
            run_fingerprint=identity['fingerprint'],
        )

    first_pass_bundle = first_pass(run_first_pass, roles=active_roles)
    first_pass_results = dict(first_pass_bundle.items())
    for role, result in first_pass_bundle.items():
        log.info("audit.agent_done", agent=role, mode="llm", risk_count=len(result.risks))
        all_risks.extend(result.risks)
        all_issues.extend(result.issues)
        planned += result.planned
        completed += result.completed
        shared_context[role] = _summarize_for_context(role, result.risks, elements)

    shared_context["handoffs"] = [
        build_review_handoff(
            from_agent=from_agent,
            to_agent=to_agent,
            risks=first_pass_results[from_agent].risks,
            payment_schedule=shared_context["payment_schedule"],
        ).to_payload()
        for from_agent, to_agent in (("legal", "finance"), ("finance", "legal"))
        if from_agent in first_pass_results and to_agent in first_pass_results
    ]

    deterministic_risks, deterministic_issues = _deterministic_audit(
        contract_text,
        dimensions=canonical_dimensions,
        contract_type=contract_type,
        legal_as_of=legal_as_of,
    )
    all_risks.extend(deterministic_risks)
    all_issues.extend(deterministic_issues)
    all_risks = _deduplicate_grounded_risks(all_risks)

    if progress_callback is not None:
        if planned_units == 0:
            progress_callback(75, "reviewing")
        progress_callback(82, "verifying")

    cross_checks = detect_conflicts(shared_context, elements)
    cross_checks.extend(build_logic_cross_checks(contract_text))
    directed = directed_review(all_risks, cross_checks, adapter_factory(), contract_text=contract_text,
                               max_calls=settings.AUDIT_DIRECTED_MAX_CALLS, deadline=deadline, clock=clock)
    exact_conflict_claim_ids = conflict_claim_ids(all_risks, cross_checks)
    recorder = (
        SqlAlchemySecondaryCallRecorder(
            contract_id=contract_id,
            audit_job_id=audit_job_id,
        )
        if contract_id is not None else None
    )
    secondary_result = SecondaryReviewer(
        adapter_factory(), recorder=recorder, clock=clock
    ).review(
        risks=all_risks,
        conflict_claim_ids=exact_conflict_claim_ids,
        deadline=deadline,
    )
    all_risks, secondary_issues = apply_secondary_decisions(
        all_risks, secondary_result
    )
    # 二次复核只能提供补充信号，发布前仍统一经过原文、依据、规则和冲突硬门禁。
    for risk in all_risks:
        risk.update(apply_risk_decision(
            risk,
            decide_risk(
                original_verified=risk.get("original_text_verified"),
                support_status=risk.get("support_relation_status", "unclear"),
                has_conflict=risk.get("claim_id") in exact_conflict_claim_ids,
                rule_statuses=[
                    str(item.get("status"))
                    for item in risk.get("rule_executions", [])
                    if isinstance(item, dict)
                ],
                parse_quality_ok=risk.get("parse_quality_ok", True),
                secondary_status=risk.get("secondary_review_status", "not_required"),
            ),
        ))
    all_issues = [
        issue for issue in all_issues
        if _candidate_issue_still_applies(issue, all_risks)
    ]
    all_issues.extend(secondary_issues)
    all_issues.extend(_unbound_conflict_issues(all_risks, cross_checks))
    if progress_callback is not None:
        progress_callback(90, "verifying")
    for r in all_risks:
        r["tier"] = classify_tier(r, exact_conflict_claim_ids)

    log.info("audit.done", total=len(all_risks), conflicts=len(cross_checks), agents=_AGENT_ORDER)
    return {
        "risks": all_risks,
        "cross_checks": cross_checks,
        "issues": [issue.model_dump(mode="json") for issue in all_issues],
        "coverage": {"planned": planned, "completed": completed},
        "timings": timings,
        "workflow": {'identity': identity, 'budget': budget.snapshot(), 'groups': group_risks(all_risks),
                     'directed_reviews': directed, 'rounds': 1},
    }


def _candidate_issue_still_applies(
    issue: ReviewIssue,
    retained_risks: list[dict],
) -> bool:
    """候选被二次复核拒绝后，不让其候选级问题污染合同终态。"""
    if issue.code not in {"EVIDENCE_UNRESOLVED", "ORIGINAL_TEXT_UNRESOLVED"}:
        return True
    matching = [
        risk for risk in retained_risks
        if risk.get("agent") == issue.agent
        and risk.get("source_window_id") == issue.window_id
    ]
    if issue.code == "ORIGINAL_TEXT_UNRESOLVED":
        return any(risk.get("original_text_verified") is not True for risk in matching)
    return any(
        (
            risk.get("evidence_status") != "supported"
            or risk.get("support_relation_status") != "supported"
        )
        and risk.get("secondary_review_status") != "confirmed"
        for risk in matching
    )


def _unbound_conflict_issues(
    risks: list[dict],
    cross_checks: list[dict],
) -> list[ReviewIssue]:
    """无法精确绑定候选的跨 Agent 冲突必须提升到合同级人工复核。"""
    has_unbound = any(
        check.get("verdict") == "conflict"
        and not conflict_claim_ids(risks, [check])
        for check in cross_checks
    )
    if not has_unbound:
        return []
    return [ReviewIssue(
        code="UNBOUND_CONFLICT",
        agent="system",
        detail="冲突项无法精确关联到候选风险，需人工复核",
    )]


def _summarize_for_context(role: str, risks: list[dict], elements: dict) -> dict:
    """把某 Agent 的结论提炼为共享上下文条目，供下游 Agent 读取（共享记忆窗口）。"""
    categories = sorted({r["category"] for r in risks})
    # 法务是否识别出关联交易（下游财务需据此做价格公允性复查）
    related_party_claim_ids = [
        str(risk["claim_id"])
        for risk in risks
        if risk.get("claim_id")
        and (
            "关联" in risk["category"]
            or "关联" in risk["original_text"]
        )
    ]
    related_party = bool(related_party_claim_ids)
    payee = str(elements.get("payee", "") or elements.get("收款账户", "")).strip()
    payee_claim_ids = [
        str(risk["claim_id"])
        for risk in risks
        if role == "finance"
        and payee
        and risk.get("claim_id")
        and payee in risk["original_text"]
    ]
    return {
        "risk_count": len(risks),
        "categories": categories,
        "related_party": related_party,
        "related_party_claim_ids": related_party_claim_ids,
        "payee_claim_ids": payee_claim_ids,
        "high_count": sum(1 for r in risks if r["level"] == "high"),
        "claims": [
            {
                "claim_id": risk.get("claim_id"),
                "category": risk.get("category"),
                "source_clause_ids": list(
                    risk.get("source_clause_ids") or ()
                ),
            }
            for risk in risks[:50]
            if risk.get("claim_id")
        ],
    }


# 维度 key → 中文名映射（对齐前端 dimensions 定义）
_DIM_LABELS: dict[str, str] = {
    "legal":       "法律条款合规性",
    "risk":        "风险条款识别",
    "payment":     "金额与付款条款",
    "breach":      "违约责任分析",
    "ip":          "知识产权条款",
    "confidentiality": "保密条款审查",
    "termination": "终止与解除条款",
    "dispute":     "争议解决条款",
}
_DIM_ALIASES = {"nda": "confidentiality"}


def _canonical_dimensions(dimensions: list[str] | None) -> list[str]:
    """统一前后端维度别名，避免同一维度导致 Agent 被错误跳过。"""
    if not dimensions:
        return []
    return list(dict.fromkeys(_DIM_ALIASES.get(key, key) for key in dimensions))


def _dimension_instruction(dimensions: list[str] | None) -> str:
    normalized = _canonical_dimensions(dimensions)
    if not normalized:
        return "本次执行全量审查。"
    unknown = sorted(set(normalized) - set(_DIM_LABELS))
    if unknown:
        raise ValueError(f"不支持的审查维度: {', '.join(unknown)}")
    labels = list(dict.fromkeys(_DIM_LABELS[key] for key in normalized))
    return "本次仅审查以下维度：" + "、".join(labels) + "。不得输出其他维度的风险。"


def _review_window_requests(
    requests: list[WindowReviewRequest],
    *,
    checkpoint,
    adapter_factory: Callable | None = None,
    max_workers: int | None = None,
    clock: Callable[[], float] = time.monotonic,
    window_completed_callback: Callable[[], None] | None = None,
) -> list[AgentReviewResult]:
    """并行计算独立窗口，并在调用线程按原顺序发布数据库结果。"""
    if not requests:
        return []
    adapter_factory = adapter_factory or get_llm_adapter
    requested_workers = (
        settings.AUDIT_MODEL_CONCURRENCY if max_workers is None else max_workers
    )
    workers = min(requested_workers, len(requests))
    if workers < 1:
        raise ValueError("max_workers 必须为正整数")

    cached: dict[int, AgentReviewResult] = {}
    pending: list[tuple[int, WindowReviewRequest]] = []
    for index, request in enumerate(requests):
        existing = checkpoint.load_valid(request)
        if existing is None:
            pending.append((index, request))
        else:
            cached[index] = existing

    def execute(request: WindowReviewRequest) -> BufferedWindowExecution:
        buffer = BufferedWindowCheckpoint()
        result = WindowReviewer(
            adapter_factory(), checkpoint=buffer, clock=clock
        ).review(request)
        return buffer.execution(result)

    futures: dict[int, Future[BufferedWindowExecution]] = {}
    with ThreadPoolExecutor(max_workers=workers) as executor:
        for index, request in pending:
            futures[index] = executor.submit(execute, request)

        ordered: list[AgentReviewResult] = []
        for index, request in enumerate(requests):
            if index in cached:
                result = cached[index]
            else:
                execution = futures[index].result()
                flush = getattr(checkpoint, "flush_execution", None)
                if flush is not None:
                    flush(request, execution)
                result = execution.result
            if result.complete and window_completed_callback is not None:
                window_completed_callback()
            ordered.append(result)
    return ordered


def _agent_audit(
    role: str,
    elements: dict,
    contract_text: str,
    shared_context: dict,
    db: "Session | None" = None,
    contract_id: int | None = None,
    dimensions: list[str] | None = None,
    contract_type: str = "",
    timings: dict[str, int] | None = None,
    audit_job_id: int | None = None,
    audit_generation: int = 0,
    deadline: float | None = None,
    clock: Callable[[], float] = time.monotonic,
    window_completed_callback: Callable[[], None] | None = None,
    legal_as_of: date | None = None,
    adapter_factory: Callable | None = None,
    run_fingerprint: str = '',
) -> AgentAuditResult:
    """单个 Agent 的窗口审查、原文核验和逐项 RAG 依据校验。"""
    agent_started = time.perf_counter()
    profile = agent_profile(role)
    dimension_instruction = _dimension_instruction(dimensions)

    # 候选风险发现阶段的参考资料；正式依据会在风险生成后逐条重新检索并校验。
    seen: set[str] = set()
    basis_lines: list[str] = []
    selected_dimensions = [
        dimension for dimension in (dimensions or [])
        if dimension in _ROLE_DIMENSIONS[role] and dimension in _DIM_TOPICS
    ]
    topics = [_DIM_TOPICS[dimension] for dimension in selected_dimensions] or profile.topics
    for topic in topics:
        for item in retrieve(
            topic,
            top_k=2,
            contract_type=contract_type,
            dimensions=selected_dimensions,
            as_of=legal_as_of,
        ):
            key = item["source"] + item["content"][:20]
            if key not in seen:
                seen.add(key)
                basis_lines.append(f"- {item['content']}（依据：{item['source']}）")
    basis_block = "\n".join(basis_lines) if basis_lines else "（没有候选参考资料，仅识别待核验问题，不得生成法规引用）"

    selected_focus = "、".join(_DIM_LABELS[dimension] for dimension in selected_dimensions)
    focus = selected_focus or profile.focus

    system_prompt = build_review_system_prompt(
        profile, focus=focus, dimension_instruction=dimension_instruction,
    )
    discovery_system_prompt = build_discovery_system_prompt(
        profile, focus=focus, dimension_instruction=dimension_instruction,
    )
    enrichment_system_prompt = build_enrichment_system_prompt(profile)

    deterministic_facts = json.dumps(
        {"payment_schedule": shared_context.get("payment_schedule", {})},
        ensure_ascii=False,
    )

    def build_user_prompt(
        review_window: ReviewWindow, page: int, page_dimensions: tuple[str, ...],
    ) -> str:
        window = review_window.window
        return (
            f"<knowledge>\n{basis_block}\n</knowledge>\n"
            f"【确定性合同事实】\n{deterministic_facts}\n"
            f"【合同基本信息】\n合同类型：{contract_type or '未指定'}\n"
            f"【已抽取的合同要素】\n{json.dumps({k: v for k, v in elements.items() if not k.startswith('has_')}, ensure_ascii=False)}\n\n"
            f"【审查窗口 {window.window_id}】\n"
            f"条款范围：{('、'.join(window.clause_ids) or '未编号段落')}\n"
            f"{_dimension_instruction(list(page_dimensions))}\n"
            f"<contract>\n{window.text}\n</contract>\n\n"
            f"当前第{page}页：按原文出现顺序、同一原文按风险类别排序，"
            f"每页最多5条，输出第{(page - 1) * 5 + 1}至{page * 5}项，跳过前页项目；"
            "仍有未输出风险时 has_more=true，否则 false。"
            "分页由系统页码控制，不输出或依赖模型游标。"
            f"请以{profile.name}的视角输出严格 JSON 对象。"
        )

    def build_discovery_prompt(
        review_window: ReviewWindow,
        page: int,
        page_dimensions: tuple[str, ...],
        accepted: tuple[RiskFinding, ...],
        page_size: int,
    ) -> str:
        window = review_window.window
        accepted_payload = [
            {
                "category": finding.category,
                "quote_hash": hashlib.sha256(
                    finding.quote.encode("utf-8")
                ).hexdigest()[:16],
                "quote_excerpt": finding.quote[:120],
            }
            for finding in accepted
        ]
        return (
            f"<knowledge>\n{basis_block}\n</knowledge>\n"
            f"【确定性合同事实】\n{deterministic_facts}\n"
            f"【合同基本信息】\n合同类型：{contract_type or '未指定'}\n"
            f"【已抽取的合同要素】\n"
            f"{json.dumps({k: v for k, v in elements.items() if not k.startswith('has_')}, ensure_ascii=False)}\n\n"
            f"【审查窗口 {window.window_id}】\n"
            f"条款范围：{('、'.join(window.clause_ids) or '未编号段落')}\n"
            f"{_dimension_instruction(list(page_dimensions))}\n"
            f"<contract>\n{window.text}\n</contract>\n\n"
            f"【已接受候选】\n{json.dumps(accepted_payload, ensure_ascii=False)}\n"
            f"当前第{page}页，每页最多{page_size}条。"
            "只输出尚未接受的新候选；仍有新候选时 has_more=true，否则 false。"
            "分页由系统控制，不输出或依赖模型游标。"
        )

    def build_enrichment_prompt(
        review_window: ReviewWindow,
        finding: RiskFinding,
        concise: bool,
    ) -> str:
        window = review_window.window
        length_instruction = (
            "reason 和 suggestion 每个字段不超过160字。"
            if concise else
            "reason 和 suggestion 每个字段不超过300字。"
        )
        return (
            f"<knowledge>\n{basis_block}\n</knowledge>\n"
            f"【合同类型】{contract_type or '未指定'}\n"
            f"【审查窗口】\n<contract>\n{window.text}\n</contract>\n"
            "【只补全这一条候选】\n"
            f"{json.dumps(finding.model_dump(mode='json'), ensure_ascii=False)}\n"
            f"{length_instruction}只输出 reason 和 suggestion。"
        )

    def build_enrichment_batch_prompt(
        review_window: ReviewWindow,
        findings: tuple[RiskFinding, ...],
        concise: bool,
    ) -> str:
        window = review_window.window
        length_instruction = (
            "reason 和 suggestion 每个字段不超过160字。"
            if concise else
            "reason 和 suggestion 每个字段不超过300字。"
        )
        candidates = [
            {
                "candidate_id": enrichment_candidate_id(
                    window.window_id, finding
                ),
                **finding.model_dump(mode="json"),
            }
            for finding in findings
        ]
        return (
            f"<knowledge>\n{basis_block}\n</knowledge>\n"
            f"【合同类型】{contract_type or '未指定'}\n"
            f"【审查窗口】\n<contract>\n{window.text}\n</contract>\n"
            "【批量补全同一窗口候选】\n"
            f"{json.dumps(candidates, ensure_ascii=False)}\n"
            f"{length_instruction}为每个 candidate_id 返回一项，只输出 items。"
        )

    checkpoint = (
        SqlAlchemyWindowCheckpoint()
        if contract_id is not None else NullWindowCheckpoint()
    )
    windows = build_contract_windows(contract_text, max_chars=8000)
    requests = [
        WindowReviewRequest(
            contract_id=contract_id,
            audit_job_id=audit_job_id,
            audit_generation=audit_generation,
            agent=role,
            dimensions=tuple(selected_dimensions),
            review_window=ReviewWindow(window),
            system_prompt=system_prompt,
            build_user_prompt=build_user_prompt,
            deadline=deadline,
            discovery_system_prompt=discovery_system_prompt,
            build_discovery_prompt=build_discovery_prompt,
            enrichment_system_prompt=enrichment_system_prompt,
            build_enrichment_prompt=build_enrichment_prompt,
            build_enrichment_batch_prompt=build_enrichment_batch_prompt,
            run_fingerprint=run_fingerprint,
        )
        for window in windows
    ]
    window_results = _review_window_requests(
        requests,
        checkpoint=checkpoint,
        adapter_factory=adapter_factory,
        max_workers=settings.AUDIT_MODEL_CONCURRENCY,
        clock=clock,
        window_completed_callback=window_completed_callback,
    )
    normalized: list[dict] = []
    issues: list[ReviewIssue] = []
    planned = completed = 0
    for result in window_results:
        planned += result.planned_windows
        completed += result.completed_windows
        issues.extend(result.issues)
        for candidate in result.candidates:
            if _is_explicit_normal_conclusion(candidate.reason, candidate.suggestion):
                continue
            candidate_payload = {
                "level": candidate.level,
                "category": candidate.category,
                "original_text": candidate.quote,
                "risk_reason": candidate.reason,
                "suggestion": candidate.suggestion,
            }
            claim = normalize_finding(
                RiskFinding(
                    level=candidate.level,
                    category=candidate.category,
                    quote=candidate.quote,
                ),
                agent=role,
                dimension=_primary_claim_dimension(
                    candidate_payload, role, selected_dimensions
                ),
                window_id=candidate.source_window_id,
                clause_ids=candidate.source_clause_ids,
            )
            risk = _risk_from_claim(
                claim,
                risk_reason=candidate.reason,
                suggestion=candidate.suggestion,
            )
            if not _candidate_matches_dimensions(risk, role, selected_dimensions):
                issues.append(ReviewIssue(
                    code="DIMENSION_MISMATCH",
                    agent=role,
                    window_id=candidate.source_window_id,
                    detail="候选风险不属于本次选择的审查维度",
                ))
                continue
            normalized.append(risk)
    if timings is not None:
        timings[f"{role}_agent_ms"] = round(
            (time.perf_counter() - agent_started) * 1000
        )
    grounding_started = time.perf_counter()
    grounded = _ground_risks(
        normalized,
        contract_text=contract_text,
        contract_type=contract_type,
        dimensions=selected_dimensions,
        legal_as_of=legal_as_of,
    )
    grounded = _deduplicate_grounded_risks(grounded)
    if timings is not None:
        timings["grounding_ms"] += round(
            (time.perf_counter() - grounding_started) * 1000
        )
    for risk in grounded:
        fact_validation = validate_candidate_facts(risk, contract_text)
        if not fact_validation.valid:
            risk["parse_quality_ok"] = False
            issues.append(ReviewIssue(
                code="FACT_VALIDATION_FAILED",
                agent=role,
                window_id=risk["source_window_id"],
                detail=fact_validation.reason,
            ))
        risk.update(apply_risk_decision(
            risk,
            decide_risk(
                original_verified=risk.get("original_text_verified"),
                support_status=risk.get("support_relation_status", "unclear"),
                has_conflict=False,
                rule_statuses=[
                    str(item.get("status"))
                    for item in risk.get("rule_executions", [])
                    if isinstance(item, dict)
                ],
                parse_quality_ok=risk.get("parse_quality_ok", True),
            ),
        ))
        if risk["original_text_verified"] is not True:
            issues.append(ReviewIssue(
                code="ORIGINAL_TEXT_UNRESOLVED", agent=role,
                window_id=risk["source_window_id"],
                detail="候选引用无法在合同正文中精确定位，需人工复核",
            ))
        if (
            risk["evidence_status"] != "supported"
            or risk["support_relation_status"] != "supported"
        ):
            issues.append(ReviewIssue(
                code="EVIDENCE_UNRESOLVED", agent=role,
                window_id=risk["source_window_id"],
                detail="候选风险缺少可支持结论的可靠依据，需人工复核",
            ))
    return AgentAuditResult(grounded, issues, planned, completed)


def _is_explicit_normal_conclusion(reason: str, suggestion: str) -> bool:
    """仅排除明确通过且无实质问题描述的模型结论，矛盾或不确定项保留复核。"""
    normal = re.search(r"无需(?:修改|调整)|无须(?:修改|调整)|可(?:继续)?保留", suggestion)
    if not normal:
        return False
    affirmative = re.search(r"未发现(?:明显)?风险|不存在(?:明显)?风险|无(?:明显)?风险|已明确|符合.*要求", reason)
    if not affirmative:
        return False
    residual = re.sub(r"未发现(?:明显)?风险|不存在(?:明显)?风险|无(?:明显)?风险|无需(?:修改|调整)|无须(?:修改|调整)", "", reason + suggestion)
    return not re.search(r"但|然而|仍|可能|不明确|未明确|缺少|缺失|不足|不合理|过高|过低|风险|应当|建议|需要|须补|需补", residual)


def _deduplicate_grounded_risks(risks: list[dict]) -> list[dict]:
    """按 claim 保留证据质量最佳的风险，质量相同时保留首次候选。"""
    selected: dict[str, dict] = {}
    evidence_rank = {"supported": 2, "partially_supported": 1}
    for risk in risks:
        claim_id = risk["claim_id"]
        previous = selected.get(claim_id)
        rank = (
            risk["original_text_verified"] is True,
            evidence_rank.get(risk["evidence_status"], 0),
            risk["support_relation_status"] == "supported",
        )
        previous_rank = (
            previous["original_text_verified"] is True,
            evidence_rank.get(previous["evidence_status"], 0),
            previous["support_relation_status"] == "supported",
        ) if previous is not None else None
        if previous_rank is None or rank > previous_rank:
            selected[claim_id] = risk
    return list(selected.values())


def _candidate_matches_dimensions(
    risk: dict,
    role: str,
    selected_dimensions: list[str],
) -> bool:
    detected = candidate_dimensions(risk)
    allowed = set(selected_dimensions) if selected_dimensions else _ROLE_DIMENSIONS[role]
    return bool(detected.intersection(allowed))


def _deterministic_audit(
    contract_text: str,
    *,
    dimensions: list[str],
    contract_type: str,
    legal_as_of: date | None = None,
) -> tuple[list[dict], list[ReviewIssue]]:
    windows = build_contract_windows(contract_text, max_chars=8000)
    risks: list[dict] = []
    for finding in find_deterministic_findings(
        contract_text, dimensions=dimensions
    ):
        source_window = next(
            (window for window in windows if finding.quote in window.text),
            windows[0],
        )
        risk = _normalize({
            "level": finding.level,
            "category": finding.category,
            "original_text": finding.quote,
            "risk_reason": finding.reason,
            "suggestion": finding.suggestion,
        }, finding.agent)
        risk["source_window_id"] = source_window.window_id
        risk["source_clause_ids"] = list(source_window.clause_ids)
        risks.append(risk)

    grounded = _ground_risks(
        risks,
        contract_text=contract_text,
        contract_type=contract_type,
        dimensions=dimensions,
        legal_as_of=legal_as_of,
    )
    issues: list[ReviewIssue] = []
    for risk in grounded:
        if (
            risk["evidence_status"] != "supported"
            or risk["support_relation_status"] != "supported"
        ):
            issues.append(ReviewIssue(
                code="EVIDENCE_UNRESOLVED",
                agent=risk["agent"],
                window_id=risk["source_window_id"],
                detail="确定性风险缺少可支持结论的可靠依据，需人工复核",
            ))
    return grounded, issues


def _ground_risks(
    risks: list[dict],
    *,
    contract_text: str | None = None,
    contract_type: str = "",
    dimensions: list[str] | None = None,
    legal_as_of: date | None = None,
) -> list[dict]:
    """为每条候选风险独立检索，只保留作用域可信的候选依据。"""
    for risk in risks:
        claim = _claim_for_grounding(risk, dimensions or [])
        plan = plan_claim(claim, contract_type=contract_type)

        def search(query):
            return retrieve(
                query.text,
                top_k=3,
                contract_type=query.contract_type,
                dimensions=dimensions or list(query.dimensions),
                as_of=legal_as_of,
                allow_exact=query.kind == "exact_reference",
            )

        execution = execute_query_plan(
            plan,
            search=search,
            validate=lambda sources: validate_support_relation(risk, sources),
            rewrite=rewrite_evidence_query,
        )
        selected_sources = list(execution.sources)
        selected_validation = execution.validation
        risk["retrieval_attempts"] = [
            attempt.as_dict(attempt=index)
            for index, attempt in enumerate(execution.attempts, start=1)
        ]
        reliable_sources = [
            source for source in selected_sources if source.get("reliable", False)
        ]
        applicability_statuses = {
            str(source.get("applicability_status", "applicable"))
            for source in reliable_sources
        }
        applicability_status = (
            "unknown_as_of"
            if "unknown_as_of" in applicability_statuses
            else "applicable"
            if reliable_sources and applicability_statuses == {"applicable"}
            else "unresolved"
        )
        risk["applicability_status"] = applicability_status
        risk["applicability_reason_codes"] = sorted({
            str(source.get("applicability_reason_code"))
            for source in reliable_sources
            if source.get("applicability_reason_code")
        })
        original_verified = _verify_original_text(
            risk.get("original_text", ""), contract_text
        )
        risk["original_text_verified"] = original_verified
        # V3 is applied after retrieval has selected authorized sources. Legacy
        # sources without an applicability field retain the historical default;
        # explicit unknown/expired applicability remains unresolved.
        v3_sources = selected_sources
        validation = verify_support(risk, v3_sources)
        supporting_sources = [
            relation["source"] for relation in validation.evidence_relations
            if relation["relation"] == "supporting"
        ]
        risk["rag_sources"] = supporting_sources
        risk["evidence_ids"] = [_evidence_id(source) for source in supporting_sources]
        if risk["retrieval_attempts"]:
            risk["retrieval_attempts"][-1]["evidence_relations"] = list(validation.evidence_relations)
        for attempt in risk["retrieval_attempts"]:
            attempt["candidate_match_status"] = attempt["support_status"]
            attempt["support_status"] = validation.status
        risk["support_relation_status"] = validation.status
        risk["support_validation_reason"] = validation.reason
        risk["support_validator_version"] = validation.version
        risk["support_validation_failed_stage"] = validation.failed_stage
        risk["support_validation_reason_code"] = validation.reason_code
        if (
            supporting_sources
            and applicability_status == "applicable"
            and original_verified is True
            and validation.status == "supported"
        ):
            risk["basis"] = "；".join(_format_source(source) for source in supporting_sources)
            risk["evidence_status"] = "supported"
        elif reliable_sources:
            risk["basis"] = NO_RELIABLE_BASIS
            risk["evidence_status"] = "partially_supported"
            risk["confidence"] = min(int(risk.get("confidence", 0)), 70)
        else:
            risk["basis"] = NO_RELIABLE_BASIS
            risk["evidence_status"] = "unsupported"
            risk["confidence"] = min(int(risk.get("confidence", 0)), 50)
        risk.update(apply_risk_decision(
            risk,
            decide_risk(
                original_verified=original_verified,
                support_status=validation.status,
                has_conflict=False,
                parse_quality_ok=risk.get("parse_quality_ok", True),
            ),
        ))
    return risks


def _verify_original_text(original_text: object, contract_text: str | None) -> bool | None:
    """验证候选原文是否存在于合同；未提供合同正文时返回 None。"""
    if contract_text is None:
        return None
    candidate = str(original_text or "").strip()
    source = contract_text or ""
    if not candidate or "全文未检出" in candidate:
        return False
    return candidate in source


def _claim_for_grounding(risk: dict, dimensions: list[str]) -> AuditClaim:
    """从兼容风险字典恢复内部 Claim，不向外部 API 暴露内部 Schema。"""
    agent = str(risk.get("agent") or "system")
    if agent not in {"legal", "finance", "system"}:
        agent = "system"
    level = str(risk.get("level") or "medium").lower()
    if level not in _VALID_LEVELS:
        level = "medium"
    category = str(risk.get("category") or "合规风险").strip()[:64]
    if len(category) < 2:
        category = "合规风险"
    quote = str(risk.get("original_text") or "全文未检出相关条款").strip()[:500]
    if len(quote) < 2:
        quote = "全文未检出相关条款"
    explicit_dimension = str(risk.get("dimension") or "").strip()
    if explicit_dimension:
        dimension = explicit_dimension[:32]
    elif agent in _ROLE_DIMENSIONS:
        dimension = _primary_claim_dimension(risk, agent, dimensions)
    else:
        dimension = "general"
    missing_information = risk.get("missing_information")
    return AuditClaim(
        agent=agent,
        level=level,
        category=category,
        dimension=dimension,
        subject=str(risk.get("subject") or "")[:128],
        action=str(risk.get("action") or "")[:256],
        condition=str(risk.get("condition") or "")[:256],
        consequence=str(risk.get("consequence") or "")[:256],
        quote=quote,
        source_window_id=risk.get("source_window_id"),
        clause_ids=list(risk.get("source_clause_ids") or ()),
        missing_information=(
            [str(value) for value in missing_information]
            if isinstance(missing_information, list) else []
        ),
    )


def _evidence_id(source: dict) -> str:
    chunk_id = source.get("chunk_id")
    if chunk_id is not None:
        return f"KC-{chunk_id}"
    payload = f"{source.get('source', '')}\0{source.get('content', '')}"
    return "EV-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _format_source(source: dict) -> str:
    name = str(source.get("source", "未知来源")).strip() or "未知来源"
    article_number = str(source.get("article_number") or "").strip()
    return f"{name} {article_number}".strip()


def _normalize(r: dict, agent: str) -> dict:
    """兼容旧调用：先建立 Claim，再适配为既有风险字典。"""
    level = str(r.get("level", "medium")).lower()
    if level not in _VALID_LEVELS:
        level = "medium"
    category = str(r.get("category", "合规风险"))[:64]
    original_text = str(r.get("original_text", ""))
    claim = AuditClaim(
        agent=agent,
        level=level,
        category=category,
        dimension=_primary_claim_dimension(r, agent, []),
        quote=original_text,
        source_window_id=r.get("source_window_id"),
        clause_ids=list(r.get("source_clause_ids") or ()),
    )
    return _risk_from_claim(
        claim,
        risk_reason=str(r.get("risk_reason", ""))[:500],
        suggestion=str(r.get("suggestion", "")),
    )


def _primary_claim_dimension(
    risk: dict,
    agent: str,
    selected_dimensions: list[str],
) -> str:
    """按稳定的产品维度顺序选择 Claim 主维度。"""
    detected = candidate_dimensions(risk)
    ordered = selected_dimensions or [
        dimension
        for dimension in _DIM_TOPICS
        if dimension in _ROLE_DIMENSIONS[agent]
    ]
    return next(
        (dimension for dimension in ordered if dimension in detected),
        ordered[0],
    )


def _risk_from_claim(
    claim: AuditClaim,
    *,
    risk_reason: str,
    suggestion: str,
) -> dict:
    """将内部 Claim 单向适配为当前 API 风险字段。"""
    return {
        "claim_id": claim.claim_id,
        "claim_status": "pending_evidence",
        "agent": claim.agent,
        "level": claim.level,
        "category": claim.category,
        "original_text": claim.quote,
        "risk_reason": risk_reason[:500],
        "basis": NO_RELIABLE_BASIS,
        "suggestion": suggestion,
        "confidence": 0,
        "evidence_status": "unsupported",
        "original_text_verified": None,
        "requires_manual_review": True,
        "support_relation_status": "unclear",
        "support_validation_reason": "尚未执行依据支持关系校验",
        "support_validator_version": SUPPORT_VALIDATOR_VERSION,
        "support_validation_failed_stage": "none",
        "support_validation_reason_code": "NOT_VALIDATED",
        "applicability_status": "unresolved",
        "applicability_reason_codes": [],
        "rule_executions": [],
        "decision_trace": {},
        "parse_quality_ok": True,
        "source_window_id": claim.source_window_id,
        "source_clause_ids": list(claim.clause_ids),
        "disclaimer": DISCLAIMER,
    }


def classify_tier(risk: dict, conflict_claim_ids: set[str] | None = None) -> str:
    """分级风险人工干预：把单条风险归入 green/yellow/red 档。

    口径与前端一致：
      - 红档：高风险，或命中敏感类别（关联交易/重大赔偿/税法争议…），或卷入跨 Agent 冲突；
      - 绿档：低风险、原文已核验且依据支持关系已核验；
      - 其余：黄档。
    """
    conflict_claim_ids = conflict_claim_ids or set()
    text = risk.get("category", "") + risk.get("original_text", "") + risk.get("basis", "")
    sensitive = any(kw in text for kw in _RED_KEYWORDS)
    in_conflict = risk.get("claim_id") in conflict_claim_ids
    if risk.get("level") == "high" or sensitive or in_conflict:
        return "red"
    if (
        risk.get("level") == "low"
        and risk.get("evidence_status") == "supported"
        and risk.get("original_text_verified") is True
    ):
        return "green"
    return "yellow"


def detect_conflicts(shared_context: dict, elements: dict) -> list[dict]:
    """交叉验证 / 冲突消解：比对两 Agent 结论，产出跨 Agent 冲突项。

    协同核心：一个 Agent 的发现触发对另一个 Agent 结论的定向复查。
    返回 [{id, from, to, trigger, action, verdict, note, category}]。
    """
    legal = shared_context.get("legal", {})
    finance = shared_context.get("finance", {})
    checks: list[dict] = []

    # 规则 1：法务识别关联交易 → 触发财务对价格公允性复查
    if legal.get("related_party"):
        checks.append({
            "id": "X1",
            "from": "legal",
            "to": "finance",
            "trigger": "法务识别合同为「关联方交易」",
            "action": "请求财务定向复查；价格公允性仍需外部业务凭证和人工判断",
            "verdict": "conflict",
            "note": "关联交易触发财务复查提示；执行状态见定向复查记录，不直接判定交易不公允。",
            "category": "关联交易",
            "claim_ids": list(legal.get("related_party_claim_ids", [])),
        })

    # 规则 2：收款账户与合同主体不一致（要素级信号）→ 财务回传法务
    payee = str(elements.get("payee", "") or elements.get("收款账户", ""))
    party_b = str(elements.get("party_b", "") or elements.get("乙方", ""))
    if payee and party_b and payee not in party_b and party_b not in payee:
        checks.append({
            "id": "X2",
            "from": "finance",
            "to": "legal",
            "trigger": "财务发现「收款账户与合同主体不一致」",
            "action": "请求法务核对收款主体；未确认前保留人工复核",
            "verdict": "conflict",
            "note": "账户文本与主体名称不一致只是待核查信号，不能直接推断舞弊或要求驳回。",
            "category": "收款账户",
            "claim_ids": list(finance.get("payee_claim_ids", [])),
        })

    # 规则 3：法务与财务都检出高风险，提示需联合决策
    if legal.get("high_count", 0) > 0 and finance.get("high_count", 0) > 0:
        checks.append({
            "id": "X3",
            "from": "legal",
            "to": "finance",
            "trigger": "法务与财务均检出高风险条款",
            "action": "汇总双 Agent 观点，交由人工终审",
            "verdict": "watch",
            "note": "法律与财务维度同时告警，建议协商并列为重点复核，进入待观察。",
            "category": "联合高风险",
        })

    return checks


# 各角色的 Mock 降级规则：(判定函数, 风险模板)。判定为真则命中该风险。
def _mock_audit(role: str, elements: dict) -> list[dict]:
    """角色化 Mock 降级：仅产出该 Agent 职责维度的规则风险。"""
    risks: list[dict] = []

    if role == "legal":
        if not elements.get("has_breach_clause"):
            risks.append(_risk(
                agent="legal", level="high", category="条款缺失",
                original_text="（全文未检出违约责任相关条款）",
                basis=retrieve("违约 违约责任 违约金"),
                suggestion="建议补充违约责任条款，明确违约情形、违约金计算方式及赔偿范围。",
                confidence=88,
            ))
        if not elements.get("has_dispute_clause"):
            risks.append(_risk(
                agent="legal", level="medium", category="条款缺失",
                original_text="（全文未检出争议解决条款）",
                basis=retrieve("争议 仲裁 诉讼 管辖"),
                suggestion="建议增加争议解决条款，明确仲裁机构或诉讼管辖法院。",
                confidence=82,
            ))
        if not elements.get("party_a") or not elements.get("party_b"):
            risks.append(_risk(
                agent="legal", level="high", category="主体缺失",
                original_text="（甲方或乙方主体信息不完整）",
                basis=[{"content": "合同主体应完整明确，否则可能影响合同效力。", "source": "合同主体条款标准", "score": 1}],
                suggestion="建议核对并补全甲乙双方的名称及主体资格信息。",
                confidence=90,
            ))

    elif role == "finance":
        if not elements.get("amount"):
            risks.append(_risk(
                agent="finance", level="high", category="要素缺失",
                original_text="（未检出明确的合同金额）",
                basis=retrieve("金额 价款 人民币"),
                suggestion="建议明确合同金额，大小写一致并标注币种。",
                confidence=85,
            ))
        if not elements.get("sign_date"):
            risks.append(_risk(
                agent="finance", level="low", category="要素缺失",
                original_text="（未检出签订日期）",
                basis=retrieve("期限 履约"),
                suggestion="建议补充合同签订日期，作为生效与期限计算的起点。",
                confidence=70,
            ))

    return risks


def _risk(*, agent: str, level: str, category: str, original_text: str, basis: list[dict], suggestion: str, confidence: int) -> dict:
    """组装单条风险为统一结构。basis 拼成可读的依据来源字符串。"""
    basis_text = "；".join(f"{b['content']}（依据：{b['source']}）" for b in basis) if basis else "（无匹配依据）"
    return {
        "agent": agent,
        "level": level,
        "category": category,
        "original_text": original_text,
        "basis": basis_text,
        "suggestion": suggestion,
        "confidence": confidence,
        "disclaimer": DISCLAIMER,
    }
