"""审查执行器：解析→审查→落库的共享逻辑。

被同步端点和 Celery 异步任务共用，保证两条路径行为一致。
真实 LLM 接入后，只有 auditor.audit_contract 内部变化，此处不动。
"""
import json
import time

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.models import Contract, Risk
from app.services.audit.auditor import audit_contract
from app.services.parser.extractor import (
    DocumentParseResult,
    extract_document,
    extract_elements,
)

log = get_logger("audit_runner")


def apply_parse_quality(contract: Contract, parsed: DocumentParseResult) -> None:
    contract.parse_source = parsed.source
    contract.ocr_confidence = parsed.ocr_confidence
    contract.requires_review = parsed.requires_review
    contract.review_reason = parsed.review_reason


def run_audit(db: Session, contract: Contract, dimensions: list[str] | None = None) -> dict:
    """串行、原子地执行单份合同审查；失败时保留进入审查前的状态。"""
    total_started = time.perf_counter()
    contract_id = contract.id
    locked_contract = (
        db.query(Contract)
        .filter(Contract.id == contract_id)
        .with_for_update()
        .populate_existing()
        .one()
    )
    previous_status = locked_contract.status
    locked_contract.status = "auditing"
    try:
        result = _run_audit_locked(db, locked_contract, dimensions)
        timings = result.pop("_timings", {})
        persist_started = time.perf_counter()
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
    except BaseException:
        db.rollback()
        try:
            restored_contract = (
                db.query(Contract).filter(Contract.id == contract_id).one()
            )
            if restored_contract.status != previous_status:
                restored_contract.status = previous_status
                db.commit()
        except BaseException as restore_exc:
            db.rollback()
            log.error(
                "audit_runner.status_restore_failed",
                contract_id=contract_id,
                error=str(restore_exc)[:240],
            )
        raise


def _run_audit_locked(
    db: Session, contract: Contract, dimensions: list[str] | None = None
) -> dict:
    """在调用方持有合同锁和事务时执行审查。"""

    parse_started = time.perf_counter()
    parsed = extract_document(contract.storage_path)
    parse_ms = round((time.perf_counter() - parse_started) * 1000)
    apply_parse_quality(contract, parsed)
    text = parsed.text
    cross_checks: list[dict] = []
    risk_count = 0
    audit_timings = {
        "legal_agent_ms": 0,
        "finance_agent_ms": 0,
        "grounding_ms": 0,
    }

    if len(text) < 200:
        contract.requires_review = True
        if not contract.review_reason:
            contract.review_reason = "合同文本长度不足 200 字"

    # 幂等：无论走短文本还是正常审查，重跑都先清理旧风险。
    db.query(Risk).filter(Risk.contract_id == contract.id).delete()

    # 前置校验：文本过短说明解析失败或扫描件，审查结论不可信，及早拦截。
    # 门槛设 200 字：正常合同最短也有甲乙方+标的+签名，200 字以下必然残缺。
    if len(text) < 200:
        log.warning("audit_runner.text_too_short", contract_id=contract.id,
                    text_length=len(text), hint="文本提取失败或文件可能为扫描件")
        placeholder = {
            "agent": "system",
            "level": "high",
            "category": "文本解析失败",
            "original_text": f"（合同文本提取长度仅 {len(text)} 字，内容严重残缺）",
            "basis": "文件可能为扫描件、图片型 PDF 或文档格式异常，文本层无法提取。",
            "suggestion": "请检查 OCR 运行时日志并人工核对扫描质量，或转换为文字版 PDF/DOCX 后重新上传。",
            "confidence": 0,
            "tier": "red",
        }
        db.add(Risk(
            contract_id=contract.id, agent="system",
            level="high", category="文本解析失败",
            original_text=placeholder["original_text"],
            basis=placeholder["basis"], suggestion=placeholder["suggestion"],
            confidence=0, tier="red", review_status="pending",
            rag_sources="[]",
        ))
        risk_count = 1
    else:
        # 避免审查时重复调 LLM，同时保留 has_*/text_length 等正则信号。
        elements = extract_elements(text)  # 先跑正则（信号字段）
        try:
            saved = json.loads(contract.elements_json or "{}")
            if any(saved.get(k) for k in ("party_a", "subject", "payment_terms")):
                elements.update({k: v for k, v in saved.items() if v and isinstance(v, str)})
        except (ValueError, AttributeError):
            pass  # elements_json 损坏时静默降级
        result = audit_contract(
            elements, text,
            db=db, contract_id=contract.id,
            dimensions=dimensions or [],
            contract_type=contract.contract_type or "",
        )
        risks = result["risks"]
        cross_checks = result["cross_checks"]
        audit_timings.update(result.get("timings", {}))

        for risk in risks:
            db.add(Risk(
                contract_id=contract.id,
                agent=risk.get("agent", "legal"),
                level=risk["level"],
                category=risk["category"],
                original_text=risk["original_text"],
                basis=risk["basis"],
                suggestion=risk["suggestion"],
                confidence=risk["confidence"],
                tier=risk.get("tier", "yellow"),
                review_status="pending",
                rag_sources=json.dumps(risk.get("rag_sources", []), ensure_ascii=False),
            ))
        risk_count = len(risks)

    if parsed.requires_review and parsed.source in {"ocr", "mixed"}:
        db.add(Risk(
            contract_id=contract.id,
            agent="system",
            level="high",
            category="扫描件识别质量不足",
            original_text=f"OCR 平均置信度：{(parsed.ocr_confidence or 0) * 100:.1f}%",
            basis=parsed.review_reason or "OCR 结果未达到自动采信门槛。",
            suggestion="请对照合同原件完成人工复核后再采信自动审查结论。",
            confidence=int(round((parsed.ocr_confidence or 0) * 100)),
            tier="red",
            review_status="pending",
            rag_sources="[]",
        ))
        risk_count += 1

    contract.status = "review_required" if contract.requires_review else "done"
    log.info(
        "audit_runner.done",
        contract_id=contract.id,
        risk_count=risk_count,
        conflicts=len(cross_checks),
    )
    return {
        "risk_count": risk_count,
        "cross_checks": cross_checks,
        "requires_review": contract.requires_review,
        "ocr_confidence": contract.ocr_confidence,
        "review_reason": contract.review_reason,
        "_timings": {"parse_ms": parse_ms, **audit_timings},
    }


def cross_checks_json(cross_checks: list[dict]) -> str:
    """把冲突项序列化为 JSON 字符串（异步任务返回值需可序列化）。"""
    return json.dumps(cross_checks, ensure_ascii=False)
