"""审查执行器：解析→审查→落库的共享逻辑。

被同步端点和 Celery 异步任务共用，保证两条路径行为一致。
真实 LLM 接入后，只有 auditor.audit_contract 内部变化，此处不动。
"""
import json
import time
from datetime import datetime, timezone
from typing import Callable

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.models.models import AuditBatchItem, Contract, Risk
from app.services.audit.auditor import audit_contract
from app.services.audit.evidence_persistence import (
    build_contract_evidence,
    replace_contract_clauses,
)
from app.services.audit.protocol import ReviewIssue
from app.services.audit.result_quality import AuditCoverage, decide_audit_status
from app.services.parser.extractor import (
    DocumentParseResult,
    extract_document,
    extract_elements,
)

log = get_logger("audit_runner")

_QUALITY_REASON_MESSAGES = {
    "INCOMPLETE_COVERAGE": "审查覆盖不完整",
    "OUTPUT_TRUNCATED": "模型输出被截断",
    "INVALID_MODEL_OUTPUT": "模型输出格式无效",
    "MODEL_TIMEOUT": "模型调用超时",
    "MODEL_UNAVAILABLE": "模型服务不可用",
    "PAGINATION_EXHAUSTED": "模型分页审查未完成",
    "EVIDENCE_UNRESOLVED": "风险依据尚未核验",
    "ORIGINAL_TEXT_UNRESOLVED": "风险原文尚未核验",
    "PARSE_QUALITY_LOW": "文档解析质量不足，需人工复核",
    "CONTRACT_TEXT_INCOMPLETE": "合同文本不完整，需人工复核",
    "SECONDARY_REVIEW_CONFLICT": "二次复核存在冲突",
    "SECONDARY_REVIEW_PENDING": "二次复核尚未完成",
    "UNBOUND_CONFLICT": "冲突项无法关联到具体风险，需人工复核",
    "AUDIT_DEADLINE_EXCEEDED": "审查达到整体时限，需人工复核",
    "DIMENSION_MISMATCH": "模型返回了本次范围外的风险",
    "FACT_VALIDATION_FAILED": "候选风险的结构化事实校验失败",
}


class StaleAuditRun(RuntimeError):
    """当前运行已被更新的审查 generation 取代。"""


def apply_parse_quality(contract: Contract, parsed: DocumentParseResult) -> None:
    contract.parse_source = parsed.source
    contract.ocr_confidence = parsed.ocr_confidence
    contract.requires_review = parsed.requires_review
    contract.review_reason = parsed.review_reason


def run_audit(
    db: Session,
    contract: Contract,
    dimensions: list[str] | None = None,
    *,
    generation: int | None = None,
    batch_item_id: int | None = None,
    execution_token: str | None = None,
    deadline: float | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> dict:
    """领取 generation 后计算，并以短事务原子发布审查结果。"""
    total_started = time.perf_counter()
    deadline = deadline if deadline is not None else clock() + settings.AUDIT_DEADLINE_SECONDS
    contract_id = contract.id
    claimed_generation = generation or 0
    owns_generation = generation is None
    previous_status = contract.status
    try:
        claimed = (
            db.query(Contract)
            .filter(Contract.id == contract_id)
            .with_for_update()
            .populate_existing()
            .one()
        )
        previous_status = claimed.status
        if owns_generation:
            claimed.audit_generation += 1
            claimed_generation = claimed.audit_generation
            claimed.status = "reviewing"
        elif claimed.audit_generation != claimed_generation:
            db.rollback()
            raise StaleAuditRun(
                f"审查运行已过期: expected={claimed_generation}, actual={claimed.audit_generation}"
            )
        storage_path = claimed.storage_path
        contract_type = claimed.contract_type or ""
        elements_json = claimed.elements_json or "{}"
        if owns_generation:
            db.commit()
        else:
            db.rollback()

        result = _compute_audit(
            db,
            contract_id=contract_id,
            storage_path=storage_path,
            contract_type=contract_type,
            elements_json=elements_json,
            dimensions=dimensions,
            audit_job_id=batch_item_id,
            audit_generation=claimed_generation,
            deadline=deadline,
            clock=clock,
        )
        # 计算阶段不持有合同锁；完成候选计算后先单独发布 validating 阶段。
        if db.in_transaction():
            db.rollback()

        timings = result.pop("_timings", {})
        parsed = result.pop("_parsed")
        risk_payloads = result.pop("_risks")
        issues = result.pop("_issues")
        coverage = result.pop("_coverage")

        validating = (
            db.query(Contract)
            .filter(Contract.id == contract_id)
            .with_for_update()
            .populate_existing()
            .one()
        )
        _assert_generation(validating, claimed_generation)
        validating_item = _locked_item(
            db,
            contract_id=contract_id,
            batch_item_id=batch_item_id,
        )
        _assert_item_fence(
            validating_item,
            generation=claimed_generation,
            execution_token=execution_token,
        )
        validating.status = "validating"
        if validating_item is not None:
            validating_item.status = "validating"
        db.commit()

        decision = decide_audit_status(risk_payloads, issues, coverage)
        quality_reasons = list(decision.reasons)
        review_reason = _review_reason(quality_reasons)
        public_issues = [_public_issue(issue) for issue in issues]
        published_risk_count = len(risk_payloads) if decision.status != "audit_failed" else 0
        result.update({
            "status": decision.status,
            "risk_count": published_risk_count,
            "requires_review": decision.requires_review,
            "review_reason": review_reason,
            "quality_reasons": quality_reasons,
            "issues": public_issues,
            "coverage": {
                "planned": coverage.planned,
                "completed": coverage.completed,
            },
        })

        persist_started = time.perf_counter()
        publishing = (
            db.query(Contract)
            .filter(Contract.id == contract_id)
            .with_for_update()
            .populate_existing()
            .one()
        )
        _assert_generation(publishing, claimed_generation)
        item = _locked_item(
            db,
            contract_id=contract_id,
            batch_item_id=batch_item_id,
        )
        _assert_item_fence(
            item,
            generation=claimed_generation,
            execution_token=execution_token,
        )
        apply_parse_quality(publishing, parsed)
        publishing.requires_review = decision.requires_review
        publishing.review_reason = review_reason
        if decision.status in {"done", "review_required"}:
            db.query(Risk).filter(
                Risk.contract_id == contract_id,
                Risk.review_status == "pending",
            ).delete(synchronize_session=False)
            clauses = replace_contract_clauses(
                db,
                contract_id=contract_id,
                audit_generation=claimed_generation,
                parsed=parsed,
            )
            db.add_all([
                _risk_model(
                    contract_id,
                    risk,
                    audit_job_id=batch_item_id,
                    contract_evidence=build_contract_evidence(risk, clauses),
                )
                for risk in risk_payloads
            ])
        publishing.status = decision.status
        if item is not None:
            item.status = "failed" if decision.status == "audit_failed" else decision.status
            item.error = None
            item.error_code = None
            item.result_json = json.dumps(
                {
                    "status": decision.status,
                    "risk_count": published_risk_count,
                    "cross_checks": result.get("cross_checks", []),
                    "requires_review": decision.requires_review,
                    "ocr_confidence": result.get("ocr_confidence"),
                    "review_reason": review_reason,
                    "quality_reasons": quality_reasons,
                    "issues": public_issues,
                    "coverage": result["coverage"],
                },
                ensure_ascii=False,
            )
            item.finished_at = datetime.now(timezone.utc)
            item.lease_expires_at = None
            item.execution_token = None
        db.commit()
        persist_ms = round((time.perf_counter() - persist_started) * 1000)
        log.info(
            "audit.performance",
            contract_id=contract_id,
            status=decision.status,
            parse_ms=int(timings.get("parse_ms", 0)),
            legal_agent_ms=int(timings.get("legal_agent_ms", 0)),
            finance_agent_ms=int(timings.get("finance_agent_ms", 0)),
            grounding_ms=int(timings.get("grounding_ms", 0)),
            persist_ms=persist_ms,
            total_ms=round((time.perf_counter() - total_started) * 1000),
        )
        return result
    except StaleAuditRun:
        db.rollback()
        raise
    except BaseException:
        db.rollback()
        try:
            restored_contract = (
                db.query(Contract)
                .filter(Contract.id == contract_id)
                .with_for_update()
                .one()
            )
            if owns_generation and claimed_generation and restored_contract.audit_generation == claimed_generation:
                restored_contract.status = previous_status
                db.commit()
            else:
                db.rollback()
        except BaseException as restore_exc:
            db.rollback()
            log.error(
                "audit_runner.status_restore_failed",
                contract_id=contract_id,
                exception_type=type(restore_exc).__name__,
            )
        raise


def _compute_audit(
    db: Session,
    *,
    contract_id: int,
    storage_path: str,
    contract_type: str,
    elements_json: str,
    dimensions: list[str] | None = None,
    audit_job_id: int | None = None,
    audit_generation: int = 0,
    deadline: float | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> dict:
    """计算审查结果，不修改合同或风险表。"""
    parse_started = time.perf_counter()
    parsed = extract_document(storage_path)
    parse_ms = round((time.perf_counter() - parse_started) * 1000)
    text = parsed.text
    cross_checks: list[dict] = []
    risk_payloads: list[dict] = []
    issues: list[ReviewIssue] = []
    coverage = AuditCoverage(1, 1)
    audit_timings = {
        "legal_agent_ms": 0,
        "finance_agent_ms": 0,
        "grounding_ms": 0,
    }

    if len(text) < 200:
        log.warning("audit_runner.text_too_short", contract_id=contract_id,
                    text_length=len(text), hint="文本提取失败或文件可能为扫描件")
        issues.append(ReviewIssue(
            code="CONTRACT_TEXT_INCOMPLETE",
            agent="parser",
            detail="合同文本长度不足 200 字",
        ))
    else:
        # 避免审查时重复调 LLM，同时保留 has_*/text_length 等正则信号。
        elements = extract_elements(text)  # 先跑正则（信号字段）
        try:
            saved = json.loads(elements_json)
            if any(saved.get(k) for k in ("party_a", "subject", "payment_terms")):
                elements.update({k: v for k, v in saved.items() if v and isinstance(v, str)})
        except (ValueError, AttributeError):
            pass  # elements_json 损坏时静默降级
        result = audit_contract(
            elements, text,
            db=db, contract_id=contract_id,
            dimensions=dimensions or [],
            contract_type=contract_type,
            audit_job_id=audit_job_id,
            audit_generation=audit_generation,
            deadline=deadline,
            clock=clock,
        )
        risk_payloads.extend(result["risks"])
        cross_checks = result["cross_checks"]
        issues.extend(_review_issues(result.get("issues", [])))
        coverage = _audit_coverage(result.get("coverage"), issues)
        audit_timings.update(result.get("timings", {}))

    if parsed.requires_review:
        issues.append(ReviewIssue(
            code="PARSE_QUALITY_LOW",
            agent="parser",
            detail="文档解析质量未达到自动采信门槛",
        ))

    risk_count = len(risk_payloads)
    log.info(
        "audit_runner.done",
        contract_id=contract_id,
        risk_count=risk_count,
        conflicts=len(cross_checks),
    )
    return {
        "risk_count": risk_count,
        "cross_checks": cross_checks,
        "ocr_confidence": parsed.ocr_confidence,
        "_parsed": parsed,
        "_risks": risk_payloads,
        "_issues": issues,
        "_coverage": coverage,
        "_timings": {"parse_ms": parse_ms, **audit_timings},
    }


def _assert_generation(contract: Contract, generation: int) -> None:
    if contract.audit_generation != generation:
        raise StaleAuditRun(
            f"审查运行已过期: expected={generation}, actual={contract.audit_generation}"
        )


def _locked_item(
    db: Session,
    *,
    contract_id: int,
    batch_item_id: int | None,
) -> AuditBatchItem | None:
    if batch_item_id is None:
        return None
    return (
        db.query(AuditBatchItem)
        .filter(
            AuditBatchItem.id == batch_item_id,
            AuditBatchItem.contract_id == contract_id,
        )
        .with_for_update()
        .one()
    )


def _assert_item_fence(
    item: AuditBatchItem | None,
    *,
    generation: int,
    execution_token: str | None,
) -> None:
    if item is None:
        return
    if item.audit_generation != generation:
        raise StaleAuditRun("审查任务 generation 与合同不一致")
    if not execution_token or item.execution_token != execution_token:
        raise StaleAuditRun("审查任务 execution token 已失效")


def _review_issues(values: object) -> list[ReviewIssue]:
    if not isinstance(values, list):
        return [ReviewIssue(
            code="INVALID_MODEL_OUTPUT",
            agent="system",
            detail="审查问题列表格式无效",
        )]
    issues: list[ReviewIssue] = []
    for value in values:
        try:
            issues.append(ReviewIssue.model_validate(value))
        except (TypeError, ValueError):
            issues.append(ReviewIssue(
                code="INVALID_MODEL_OUTPUT",
                agent="system",
                detail="审查问题条目格式无效",
            ))
    return issues


def _audit_coverage(value: object, issues: list[ReviewIssue]) -> AuditCoverage:
    try:
        if not isinstance(value, dict):
            raise ValueError("coverage must be an object")
        planned = value["planned"]
        completed = value["completed"]
        if type(planned) is not int or type(completed) is not int:
            raise ValueError("coverage counts must be integers")
        return AuditCoverage(
            planned=planned,
            completed=completed,
        )
    except (KeyError, TypeError, ValueError):
        issues.append(ReviewIssue(
            code="INVALID_MODEL_OUTPUT",
            agent="system",
            detail="审查覆盖率格式无效",
        ))
        return AuditCoverage(0, 0)


def _review_reason(reasons: list[str]) -> str | None:
    if not reasons:
        return None
    return "；".join(_QUALITY_REASON_MESSAGES.get(code, "审查质量需要人工复核") for code in reasons)


def _public_issue(issue: ReviewIssue) -> dict:
    return {
        "code": issue.code,
        "agent": issue.agent,
        "window_id": issue.window_id,
        "detail": _QUALITY_REASON_MESSAGES.get(issue.code, "审查质量需要人工复核"),
    }


def _risk_model(
    contract_id: int,
    risk: dict,
    *,
    audit_job_id: int | None = None,
    contract_evidence: list[dict] | None = None,
) -> Risk:
    return Risk(
        contract_id=contract_id,
        audit_job_id=audit_job_id,
        agent=risk.get("agent", "legal"),
        level=risk["level"],
        category=risk["category"],
        original_text=risk["original_text"],
        risk_reason=risk.get("risk_reason", ""),
        basis=risk["basis"],
        suggestion=risk["suggestion"],
        confidence=risk["confidence"],
        tier=risk.get("tier", "yellow"),
        review_status="pending",
        rag_sources=json.dumps(risk.get("rag_sources", []), ensure_ascii=False),
        evidence_status=risk.get("evidence_status", "unsupported"),
        original_text_verified=risk.get("original_text_verified"),
        requires_manual_review=risk.get("requires_manual_review", True),
        support_relation_status=risk.get("support_relation_status", "unclear"),
        support_validation_reason=risk.get("support_validation_reason", ""),
        support_validator_version=risk.get("support_validator_version", "unvalidated"),
        secondary_review_status=risk.get("secondary_review_status", "not_required"),
        secondary_review_reason=risk.get("secondary_review_reason", ""),
        claim_id=risk.get("claim_id"),
        claim_status=risk.get("claim_status", "pending_evidence"),
        source_window_id=risk.get("source_window_id"),
        source_clause_ids_json=json.dumps(
            risk.get("source_clause_ids", []), ensure_ascii=False
        ),
        evidence_ids_json=json.dumps(risk.get("evidence_ids", []), ensure_ascii=False),
        retrieval_attempts_json=json.dumps(
            risk.get("retrieval_attempts", []), ensure_ascii=False
        ),
        contract_evidence_json=json.dumps(
            contract_evidence or [], ensure_ascii=False
        ),
    )


def cross_checks_json(cross_checks: list[dict]) -> str:
    """把冲突项序列化为 JSON 字符串（异步任务返回值需可序列化）。"""
    return json.dumps(cross_checks, ensure_ascii=False)
