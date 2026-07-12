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


def run_audit(db: Session, contract: Contract) -> dict:
    """对单份合同执行审查并落库。

    返回 {"risk_count": int, "cross_checks": [...]}：
      - 风险清单（含 tier 分档）落库到 risks 表；
      - 交叉验证冲突项为审查态动态结果，不落库，随本次响应返回。
    """
    contract.status = "auditing"
    db.commit()

    text = extract_text(contract.storage_path)
    elements = extract_elements(text)
    result = audit_contract(elements, text, db=db, contract_id=contract.id)
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
