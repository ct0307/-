"""审查执行器：解析→审查→落库的共享逻辑。

被同步端点和 Celery 异步任务共用，保证两条路径行为一致。
真实 LLM 接入后，只有 auditor.audit_contract 内部变化，此处不动。
"""
import json

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.models import Contract, Risk
from app.services.audit.auditor import audit_contract
from app.services.parser.extractor import extract_elements, extract_text

log = get_logger("audit_runner")


def run_audit(db: Session, contract: Contract, dimensions: list[str] | None = None) -> dict:
    """对单份合同执行审查并落库。dimensions 为空/None 时全量审查。"""
    contract.status = "auditing"
    db.commit()

    text = extract_text(contract.storage_path)
    # 优先用 parse 时已 LLM 精抽的要素（elements_json），无则实时正则提取。
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

    # 幂等：重跑先清旧风险
    db.query(Risk).filter(Risk.contract_id == contract.id).delete()
    for r in risks:
        db.add(Risk(
            contract_id=contract.id,
            agent=r.get("agent", "legal"),
            level=r["level"],
            category=r["category"],
            original_text=r["original_text"],
            basis=r["basis"],
            suggestion=r["suggestion"],
            confidence=r["confidence"],
            tier=r.get("tier", "yellow"),
            review_status="pending",
            rag_sources=json.dumps(r.get("rag_sources", []), ensure_ascii=False),
        ))
    contract.status = "done"
    db.commit()
    log.info("audit_runner.done", contract_id=contract.id, risk_count=len(risks), conflicts=len(cross_checks))
    return {"risk_count": len(risks), "cross_checks": cross_checks}


def cross_checks_json(cross_checks: list[dict]) -> str:
    """把冲突项序列化为 JSON 字符串（异步任务返回值需可序列化）。"""
    return json.dumps(cross_checks, ensure_ascii=False)
