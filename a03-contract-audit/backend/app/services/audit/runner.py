"""审查执行器：解析→审查→落库的共享逻辑。

被同步端点和 Celery 异步任务共用，保证两条路径行为一致。
真实 LLM 接入后，只有 auditor.audit_contract 内部变化，此处不动。
"""
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.models import Contract, Risk
from app.services.audit.auditor import audit_contract
from app.services.parser.extractor import extract_elements, extract_text

log = get_logger("audit_runner")


def run_audit(db: Session, contract: Contract) -> int:
    """对单份合同执行审查并落库，返回风险条数。"""
    contract.status = "auditing"
    db.commit()

    text = extract_text(contract.storage_path)
    elements = extract_elements(text)
    results = audit_contract(elements, text)

    # 幂等：重跑先清旧风险
    db.query(Risk).filter(Risk.contract_id == contract.id).delete()
    for r in results:
        db.add(Risk(
            contract_id=contract.id,
            agent=r.get("agent", "legal"),
            level=r["level"],
            category=r["category"],
            original_text=r["original_text"],
            basis=r["basis"],
            suggestion=r["suggestion"],
            confidence=r["confidence"],
            review_status="pending",
        ))
    contract.status = "done"
    db.commit()
    log.info("audit_runner.done", contract_id=contract.id, risk_count=len(results))
    return len(results)
