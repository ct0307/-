"""审查执行器：解析→审查→落库的共享逻辑。

被同步端点和 Celery 异步任务共用，保证两条路径行为一致。
真实 LLM 接入后，只有 auditor.audit_contract 内部变化，此处不动。
"""
import json
import time
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.models import AuditBatchItem, Contract, Risk
from app.services.audit.auditor import audit_contract
from app.services.parser.extractor import (
    DocumentParseResult,
    extract_document,
    extract_elements,
)

log = get_logger("audit_runner")


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
) -> dict:
    """领取 generation 后计算，并以短事务原子发布审查结果。"""
    total_started = time.perf_counter()
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
            claimed.status = "auditing"
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
        )
        # 发布前清理计算阶段可能打开的只读事务。
        if db.in_transaction():
            db.rollback()

        timings = result.pop("_timings", {})
        parsed = result.pop("_parsed")
        risk_payloads = result.pop("_risks")
        persist_started = time.perf_counter()
        publishing = (
            db.query(Contract)
            .filter(Contract.id == contract_id)
            .with_for_update()
            .populate_existing()
            .one()
        )
        if publishing.audit_generation != claimed_generation:
            db.rollback()
            raise StaleAuditRun(
                f"审查运行已过期: expected={claimed_generation}, actual={publishing.audit_generation}"
            )
        item = None
        if batch_item_id is not None:
            item = (
                db.query(AuditBatchItem)
                .filter(
                    AuditBatchItem.id == batch_item_id,
                    AuditBatchItem.contract_id == contract_id,
                )
                .with_for_update()
                .one()
            )
            if item.audit_generation != claimed_generation:
                db.rollback()
                raise StaleAuditRun(
                    "审查任务 generation 与合同不一致"
                )
            if not execution_token or item.execution_token != execution_token:
                db.rollback()
                raise StaleAuditRun("审查任务 execution token 已失效")
        apply_parse_quality(publishing, parsed)
        if len(parsed.text) < 200:
            publishing.requires_review = True
            publishing.review_reason = publishing.review_reason or "合同文本长度不足 200 字"
        if result.get("requires_review"):
            publishing.requires_review = True
            publishing.review_reason = result.get("review_reason") or publishing.review_reason
        db.query(Risk).filter(
            Risk.contract_id == contract_id,
            Risk.review_status == "pending",
        ).delete(synchronize_session=False)
        db.add_all([
            _risk_model(contract_id, risk, audit_job_id=batch_item_id)
            for risk in risk_payloads
        ])
        publishing.status = "review_required" if publishing.requires_review else "done"
        if item is not None:
            item.status = "done"
            item.error = None
            item.error_code = None
            item.result_json = json.dumps(
                {
                    "risk_count": int(result.get("risk_count", 0)),
                    "cross_checks": result.get("cross_checks", []),
                    "requires_review": bool(result.get("requires_review", False)),
                    "ocr_confidence": result.get("ocr_confidence"),
                    "review_reason": result.get("review_reason"),
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
            status="success",
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
) -> dict:
    """计算审查结果，不修改合同或风险表。"""
    parse_started = time.perf_counter()
    parsed = extract_document(storage_path)
    parse_ms = round((time.perf_counter() - parse_started) * 1000)
    text = parsed.text
    cross_checks: list[dict] = []
    risk_payloads: list[dict] = []
    audit_timings = {
        "legal_agent_ms": 0,
        "finance_agent_ms": 0,
        "grounding_ms": 0,
    }

    # 前置校验：文本过短说明解析失败或扫描件，审查结论不可信，及早拦截。
    # 门槛设 200 字：正常合同最短也有甲乙方+标的+签名，200 字以下必然残缺。
    if len(text) < 200:
        log.warning("audit_runner.text_too_short", contract_id=contract_id,
                    text_length=len(text), hint="文本提取失败或文件可能为扫描件")
        risk_payloads.append({
            "agent": "system",
            "level": "high",
            "category": "文本解析失败",
            "original_text": f"（合同文本提取长度仅 {len(text)} 字，内容严重残缺）",
            "risk_reason": "合同文本严重残缺，无法完成可靠审查。",
            "basis": "文件可能为扫描件、图片型 PDF 或文档格式异常，文本层无法提取。",
            "suggestion": "请检查 OCR 运行时日志并人工核对扫描质量，或转换为文字版 PDF/DOCX 后重新上传。",
            "confidence": 0,
            "tier": "red",
            "evidence_status": "unsupported",
            "original_text_verified": False,
            "requires_manual_review": True,
        })
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
        )
        risk_payloads.extend(result["risks"])
        cross_checks = result["cross_checks"]
        audit_timings.update(result.get("timings", {}))

    if parsed.requires_review and parsed.source in {"ocr", "mixed"}:
        risk_payloads.append({
            "agent": "system",
            "level": "high",
            "category": "扫描件识别质量不足",
            "original_text": f"OCR 平均置信度：{(parsed.ocr_confidence or 0) * 100:.1f}%",
            "risk_reason": "OCR 质量未达到自动采信门槛。",
            "basis": parsed.review_reason or "OCR 结果未达到自动采信门槛。",
            "suggestion": "请对照合同原件完成人工复核后再采信自动审查结论。",
            "confidence": int(round((parsed.ocr_confidence or 0) * 100)),
            "tier": "red",
            "evidence_status": "unsupported",
            "original_text_verified": False,
            "requires_manual_review": True,
        })

    risk_count = len(risk_payloads)
    risk_requires_review = any(
        bool(risk.get("requires_manual_review")) for risk in risk_payloads
    )
    requires_review = parsed.requires_review or len(text) < 200 or risk_requires_review
    review_reason = parsed.review_reason or (
        "合同文本长度不足 200 字" if len(text) < 200
        else "存在证据不足或原文未核验的风险" if risk_requires_review
        else None
    )
    log.info(
        "audit_runner.done",
        contract_id=contract_id,
        risk_count=risk_count,
        conflicts=len(cross_checks),
    )
    return {
        "risk_count": risk_count,
        "cross_checks": cross_checks,
        "requires_review": requires_review,
        "ocr_confidence": parsed.ocr_confidence,
        "review_reason": review_reason,
        "_parsed": parsed,
        "_risks": risk_payloads,
        "_timings": {"parse_ms": parse_ms, **audit_timings},
    }


def _risk_model(
    contract_id: int,
    risk: dict,
    *,
    audit_job_id: int | None = None,
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
    )


def cross_checks_json(cross_checks: list[dict]) -> str:
    """把冲突项序列化为 JSON 字符串（异步任务返回值需可序列化）。"""
    return json.dumps(cross_checks, ensure_ascii=False)
