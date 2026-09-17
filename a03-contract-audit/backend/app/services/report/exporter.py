"""报表导出：Excel 风险台账 + 看板聚合数据。"""
import io
import hashlib
import json
import re
from datetime import datetime, timezone

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.models.models import AuditBatchItem, Contract, ContractClause, Rectification, Risk
from app.services.report.renderers import export_report_docx, export_report_xlsx
from app.services.report.payment_insights import analyze_payments
from app.services.audit.result_snapshot import quality_snapshot, safe_coverage

DepartmentScope = str | set[str] | None

_TERMINAL_SUCCESS = {"done", "review_required"}
_FAILED = {"failed"}
_XML_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _json_value(value, fallback):
    try:
        parsed = json.loads(value or "")
        return parsed if isinstance(parsed, type(fallback)) else fallback
    except (TypeError, ValueError):
        return fallback


def _iso(value) -> str | None:
    return value.isoformat() if value is not None else None


def _clean_text(value) -> str:
    return _XML_CONTROL_RE.sub("", str(value or ""))


def _excel_value(value):
    value = _clean_text(value)
    return f"'{value}" if value.startswith(("=", "+", "-", "@")) else value


def _normalize_contract_ids(contract_ids: list[int] | None) -> list[int] | None:
    if contract_ids is None:
        return None
    if not contract_ids or len(contract_ids) > 200:
        raise ValueError("contract_ids 必须包含 1 到 200 个合同 ID")
    if any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in contract_ids):
        raise ValueError("合同 ID 必须为正整数")
    return list(dict.fromkeys(contract_ids))


def build_report_snapshot(
    db: Session,
    contract_ids: list[int] | None = None,
    department_scope: DepartmentScope = None,
) -> dict:
    """在当前数据库事务内构建可序列化、可复现的统一报告快照。"""
    connection = db.connection()
    if connection.dialect.name == "sqlite" and not connection.connection.driver_connection.in_transaction:
        connection.execute(text("BEGIN"))
    selected_ids = _normalize_contract_ids(contract_ids)
    query = db.query(Contract).filter(Contract.deleted_at.is_(None))
    if selected_ids is not None:
        existing = {row[0] for row in db.query(Contract.id).filter(Contract.id.in_(selected_ids), Contract.deleted_at.is_(None)).all()}
        missing = set(selected_ids) - existing
        if missing:
            raise LookupError(f"合同不存在或已删除：{sorted(missing)}")
        query = query.filter(Contract.id.in_(selected_ids))
    query = _scope_contracts(query, department_scope)
    contracts = query.order_by(Contract.id).all()
    if selected_ids is not None:
        accessible = {row.id for row in contracts}
        if accessible != set(selected_ids):
            raise PermissionError("所选合同包含无权访问的数据")

    ids = [row.id for row in contracts]
    jobs = [] if not ids else db.query(AuditBatchItem).filter(
        AuditBatchItem.contract_id.in_(ids)
    ).order_by(AuditBatchItem.contract_id, AuditBatchItem.audit_generation.desc(), AuditBatchItem.id.desc()).all()
    latest_jobs: dict[int, AuditBatchItem] = {}
    for job in jobs:
        latest_jobs.setdefault(job.contract_id, job)

    risk_query = db.query(Risk).filter(Risk.contract_id.in_(ids)) if ids else None
    all_risks = risk_query.order_by(Risk.contract_id, Risk.id).all() if risk_query is not None else []
    visible_risks = []
    notes: list[str] = []
    for risk in all_risks:
        job = latest_jobs.get(risk.contract_id)
        if job is None:
            if risk.audit_job_id is None:
                visible_risks.append(risk)
            continue
        if job.status in _TERMINAL_SUCCESS and risk.audit_job_id == job.id:
            visible_risks.append(risk)

    contract_rows = []
    clauses_by_contract = {}
    if ids:
        for clause in db.query(ContractClause).filter(ContractClause.contract_id.in_(ids)).order_by(ContractClause.char_start, ContractClause.id).all():
            job = latest_jobs.get(clause.contract_id)
            if job and clause.audit_generation == job.audit_generation and job.status in _TERMINAL_SUCCESS:
                clauses_by_contract.setdefault(clause.contract_id, []).append(clause.content)
    for contract in contracts:
        job = latest_jobs.get(contract.id)
        elements = _json_value(contract.elements_json, {})
        job_payload = _json_value(job.result_json, {}) if job else {}
        quality = quality_snapshot(job, contract) if job else None
        contract_risks = [r for r in visible_risks if r.contract_id == contract.id]
        contract_rows.append({
            "id": contract.id,
            "filename": _clean_text(contract.filename),
            "contract_type": contract.contract_type or "",
            "suggested_type": contract.suggested_type or "",
            "type_confidence": contract.type_confidence,
            "type_evidence": _json_value(contract.type_evidence_json, []),
            "department": contract.department or "",
            "status": contract.status,
            "content_sha256": contract.content_sha256,
            "audit_generation": job.audit_generation if job else contract.audit_generation,
            "elements": elements,
            "party_a": str(elements.get("party_a") or "—"),
            "subject": str(elements.get("subject") or "—"),
            "payment_terms": str(elements.get("payment_terms") or "—"),
            "amount": str(elements.get("amount") or "—"),
            "risk_high": sum(r.level == "high" for r in contract_risks),
            "risk_medium": sum(r.level == "medium" for r in contract_risks),
            "risk_low": sum(r.level == "low" for r in contract_risks),
            "risk_total": len(contract_risks),
            "element_evidence": _json_value(contract.element_evidence_json, {}),
            "parse_source": contract.parse_source,
            "ocr_confidence": quality.ocr_confidence if quality else contract.ocr_confidence,
            "requires_review": quality.requires_review if quality else bool(contract.requires_review),
            "review_reason": (job.error or quality.review_reason) if job else contract.review_reason,
            "job_id": job.id if job else None,
            "job_status": job.status if job else None,
            "coverage": safe_coverage(job_payload.get("coverage")),
            "cross_checks": job_payload.get("cross_checks", []) if isinstance(job_payload.get("cross_checks", []), list) else [],
            "created_at": _iso(contract.created_at),
            "finished_at": _iso(job.finished_at) if job else None,
            "payment_analysis": analyze_payments("\n".join(clauses_by_contract.get(contract.id, []))),
        })
        if job is None:
            notes.append(f"{contract.filename}：无审查任务，风险为历史兼容数据且无任务质量信息。")
        elif job.status in _FAILED:
            notes.append(f"{contract.filename}：最新审查任务失败，未将旧任务风险作为当前结果。")

    filename_by_id = {row.id: _clean_text(row.filename) for row in contracts}
    risk_rows = [{
        "id": risk.id,
        "contract_id": risk.contract_id,
        "filename": filename_by_id.get(risk.contract_id, ""),
        "audit_job_id": risk.audit_job_id,
        "agent": risk.agent,
        "level": risk.level,
        "category": _clean_text(risk.category),
        "original_text": _clean_text(risk.original_text),
        "risk_reason": _clean_text(risk.risk_reason),
        "basis": _clean_text(risk.basis),
        "suggestion": _clean_text(risk.suggestion),
        "confidence": risk.confidence,
        "tier": risk.tier,
        "evidence_status": risk.evidence_status,
        "original_text_verified": risk.original_text_verified,
        "requires_manual_review": bool(risk.requires_manual_review),
        "review_status": risk.review_status,
        "support_relation_status": risk.support_relation_status,
        "support_validation_reason": _clean_text(risk.support_validation_reason),
        "claim_id": risk.claim_id,
        "claim_status": risk.claim_status,
        "secondary_review_status": risk.secondary_review_status,
        "secondary_review_reason": _clean_text(risk.secondary_review_reason),
        "contract_evidence": _json_value(risk.contract_evidence_json, []),
        "rag_sources": _json_value(risk.rag_sources, []),
        "created_at": _iso(risk.created_at),
    } for risk in visible_risks]

    visible_risk_ids = {row["id"] for row in risk_rows}
    rectifications = []
    if visible_risk_ids:
        for row in db.query(Rectification).filter(Rectification.risk_id.in_(visible_risk_ids)).order_by(Rectification.id).all():
            rectifications.append({
                "id": row.id, "risk_id": row.risk_id, "contract": _clean_text(row.contract),
                "risk": _clean_text(row.risk), "level": row.level, "owner": _clean_text(row.owner),
                "status": row.status, "created": row.created, "due": row.due,
                "note": _clean_text(row.note), "created_at": _iso(row.created_at),
            })

    categories = sorted({row["category"] for row in risk_rows})
    matrix_rows = []
    for contract in contract_rows:
        counts = [sum(1 for risk in risk_rows if risk["contract_id"] == contract["id"] and risk["category"] == category) for category in categories]
        matrix_rows.append({"contract_id": contract["id"], "filename": contract["filename"], "counts": counts})
    statuses = [row["job_status"] for row in contract_rows]
    summary = {
        "total": len(contract_rows),
        "completed": sum(value == "done" for value in statuses),
        "review_required": sum(value == "review_required" for value in statuses),
        "failed": sum(value in _FAILED for value in statuses),
        "unreviewed": sum(value is None for value in statuses),
        "running": sum(value is not None and value not in _TERMINAL_SUCCESS | _FAILED for value in statuses),
        "risks": len(risk_rows),
        "high": sum(row["level"] == "high" for row in risk_rows),
        "medium": sum(row["level"] == "medium" for row in risk_rows),
        "low": sum(row["level"] == "low" for row in risk_rows),
        "supported": sum(row["evidence_status"] == "supported" and row["original_text_verified"] is True for row in risk_rows),
    }
    content = {
        "contract_ids": ids, "summary": summary, "contracts": contract_rows,
        "risks": risk_rows, "rectifications": rectifications,
        "matrix": {"categories": categories, "rows": matrix_rows}, "notes": notes,
    }
    notes.extend(["风险按各合同最新审查任务统计；失败或未完成任务不使用旧结果替代。", "证据已核验需原文精确定位且依据支持；无高风险不等于合规。", "上传日期用于导入趋势，不能解释为当日审查或整改效果。"])
    report_id = hashlib.sha256(json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return {"report_id": report_id, "generated_at": datetime.now(timezone.utc).isoformat(), **content}


def _scope_contracts(query, department_scope: DepartmentScope):
    query = query.filter(Contract.deleted_at.is_(None))
    if isinstance(department_scope, str):
        return query.filter(Contract.department == department_scope)
    if department_scope is not None:
        return query.filter(Contract.department.in_(department_scope))
    return query

# 报表时间分段 → 趋势坐标轴标签。真实系统应有时间序列聚合表，
# 当前 DB 无历史快照，趋势轴用固定档位标签 + 真实总量末点，稀疏时以 mode 标注。
_RANGE_LABELS = {
    "month": ["第1周", "第2周", "第3周", "第4周", "第5周", "第6周", "本周"],
    "quarter": ["1月", "2月", "3月", "4月", "5月", "6月", "本月"],
    "year": ["Q1", "Q2", "Q3", "Q4", "上年Q3", "上年Q4", "本季"],
}

def _elem(contract, key: str) -> str:
    """从 elements_json 安全取值，NULL或解析失败返回 '—'。"""
    try:
        return json.loads(contract.elements_json or "{}").get(key) or "—"
    except (ValueError, AttributeError):
        return "—"


# 台账列定义：(表头, Risk/Contract 取值函数, 列宽)
_LEDGER_COLUMNS = [
    ("合同", lambda r, c: c.filename, 28),
    ("甲方", lambda r, c: _elem(c, "party_a"), 22),
    ("合同标的", lambda r, c: _elem(c, "subject"), 32),
    ("收付款节点", lambda r, c: _elem(c, "payment_terms"), 36),
    ("合同类型", lambda r, c: c.contract_type or "—", 14),
    ("负责 Agent", lambda r, c: _AGENT_LABEL.get(r.agent, r.agent), 16),
    ("风险类别", lambda r, c: r.category, 14),
    ("风险等级", lambda r, c: {"high": "高", "medium": "中", "low": "低"}.get(r.level, r.level), 10),
    ("原文引用", lambda r, c: r.original_text, 40),
    ("依据来源", lambda r, c: r.basis, 40),
    ("修改建议", lambda r, c: r.suggestion, 40),
    ("置信度", lambda r, c: r.confidence, 8),
    ("复核状态", lambda r, c: {"pending": "待处理", "confirmed": "已确认", "ignored": "已忽略", "to_modify": "需修改"}.get(r.review_status, r.review_status), 10),
]

_LEVEL_LABEL = {"high": "高", "medium": "中", "low": "低"}
_STATUS_LABEL = {"pending": "待处理", "confirmed": "已确认", "ignored": "已忽略", "to_modify": "需修改"}
_AGENT_LABEL = {"legal": "法务专家 Agent", "finance": "财务会计 Agent"}


def export_risk_ledger(
    db: Session,
    contract_ids: list[int] | None = None,
    *,
    department_scope: DepartmentScope = None,
) -> bytes:
    """生成 Excel 风险台账（openpyxl），返回文件字节流。

    contract_ids 为空则导出全部合同的风险。
    """
    q = db.query(Risk, Contract).join(Contract, Risk.contract_id == Contract.id)
    q = _scope_contracts(q, department_scope)
    if contract_ids:
        q = q.filter(Contract.id.in_(contract_ids))
    rows = q.order_by(Contract.id, Risk.level).all()

    wb = Workbook()
    ws = wb.active
    ws.title = "风险台账"

    header_fill = PatternFill("solid", fgColor="305496")
    header_font = Font(color="FFFFFF", bold=True)
    for col_idx, (title, _, width) in enumerate(_LEDGER_COLUMNS, start=1):
        cell = ws.cell(row=1, column=col_idx, value=title)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")
        ws.column_dimensions[get_column_letter(col_idx)].width = width

    for row_idx, (risk, contract) in enumerate(rows, start=2):
        for col_idx, (_, getter, _) in enumerate(_LEDGER_COLUMNS, start=1):
            cell = ws.cell(row=row_idx, column=col_idx, value=getter(risk, contract))
            cell.alignment = Alignment(vertical="top", wrap_text=True)

    ws.freeze_panes = "A2"  # 冻结表头

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def contracts_metadata(db: Session, *, department_scope: DepartmentScope = None) -> list[dict]:
    """合同选择器与报告采用相同的任务代次和质量口径。"""
    return list(reversed(build_report_snapshot(db, department_scope=department_scope)["contracts"]))


def dashboard_summary(db: Session, *, department_scope: DepartmentScope = None) -> dict:
    """看板聚合：风险等级分布、类别 Top、合同/复核状态分布、总量。供前端 ECharts。"""
    total_contracts = _scope_contracts(db.query(func.count(Contract.id)), department_scope).scalar() or 0
    total_risks = _scope_contracts(
        db.query(func.count(Risk.id)).join(Contract), department_scope
    ).scalar() or 0

    # 风险等级分布
    level_rows = _scope_contracts(
        db.query(Risk.level, func.count(Risk.id)).join(Contract), department_scope
    ).group_by(Risk.level).all()
    level_dist = {_LEVEL_LABEL.get(lv, lv): cnt for lv, cnt in level_rows}

    # 风险类别 Top（降序）
    cat_rows = _scope_contracts(
        db.query(Risk.category, func.count(Risk.id)).join(Contract), department_scope
    ).group_by(Risk.category).order_by(func.count(Risk.id).desc()).all()
    category_dist = [{"category": cat, "count": cnt} for cat, cnt in cat_rows]

    # 合同状态分布
    cstatus_rows = _scope_contracts(
        db.query(Contract.status, func.count(Contract.id)), department_scope
    ).group_by(Contract.status).all()
    contract_status = {st: cnt for st, cnt in cstatus_rows}

    # 复核状态分布
    rstatus_rows = _scope_contracts(
        db.query(Risk.review_status, func.count(Risk.id)).join(Contract), department_scope
    ).group_by(Risk.review_status).all()
    review_status = {_STATUS_LABEL.get(st, st): cnt for st, cnt in rstatus_rows}

    # 智能体维度分布（多智能体协同：法务/财务各查出多少风险）
    agent_rows = _scope_contracts(
        db.query(Risk.agent, func.count(Risk.id)).join(Contract), department_scope
    ).group_by(Risk.agent).all()
    agent_distribution = {_AGENT_LABEL.get(ag, ag): cnt for ag, cnt in agent_rows}

    return {
        "total_contracts": total_contracts,
        "total_risks": total_risks,
        "level_distribution": level_dist,
        "category_distribution": category_dist,
        "contract_status": contract_status,
        "review_status": review_status,
        "agent_distribution": agent_distribution,
    }


def report_summary(db: Session, range_key: str = "month", *, department_scope: DepartmentScope = None) -> dict:
    """保留旧接口结构；通过率无人工结论支持时不作合规推断。"""
    from collections import Counter
    snapshot = build_report_snapshot(db, department_scope=department_scope)
    contracts, risks, summary = snapshot["contracts"], snapshot["risks"], snapshot["summary"]
    names = {c["id"]: c["department"] or "未分类" for c in contracts}
    depts = Counter(names[r["contract_id"]] for r in risks)
    tops = Counter(r["category"] for r in risks if r["level"] == "high")
    days = sorted({c["created_at"][:10] for c in contracts if c["created_at"]})
    trend = {"labels": days, "total": [], "pass": [], "risk": []}
    for day in days:
        current = [c for c in contracts if c["created_at"] and c["created_at"][:10] <= day]
        trend["total"].append(len(current))
        trend["pass"].append(0)
        trend["risk"].append(sum(c["risk_high"] > 0 for c in current))
    return {
        "kpi": {"total": summary["total"], "pass": 0, "risk": summary["high"], "time": "—"},
        "kpiTrend": {"total": "", "pass": "", "risk": "", "time": ""},
        "trend": trend,
        "donut": [{"name": label, "value": summary[key]} for key, label in (("high", "高风险"), ("medium", "中风险"), ("low", "低风险"))],
        "depts": [{"name": name, "risk": count, "money": "—"} for name, count in depts.most_common()],
        "tops": [{"name": name, "value": count} for name, count in tops.most_common(5)],
        "mode": "real" if len(days) >= 2 else "sparse",
        "notes": ["旧版通过率字段不再推断合规；请使用证据报告中的审查质量状态。"],
    }
