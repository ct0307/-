"""报表导出：Excel 风险台账 + 看板聚合数据。"""
import io

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.models import Contract, Risk

# 台账列定义：(表头, Risk/Contract 取值函数, 列宽)
_LEDGER_COLUMNS = [
    ("合同", lambda r, c: c.filename, 28),
    ("合同类型", lambda r, c: c.contract_type or "-", 14),
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


def export_risk_ledger(db: Session, contract_ids: list[int] | None = None) -> bytes:
    """生成 Excel 风险台账（openpyxl），返回文件字节流。

    contract_ids 为空则导出全部合同的风险。
    """
    q = db.query(Risk, Contract).join(Contract, Risk.contract_id == Contract.id)
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


def dashboard_summary(db: Session) -> dict:
    """看板聚合：风险等级分布、类别 Top、合同/复核状态分布、总量。供前端 ECharts。"""
    total_contracts = db.query(func.count(Contract.id)).scalar() or 0
    total_risks = db.query(func.count(Risk.id)).scalar() or 0

    # 风险等级分布
    level_rows = db.query(Risk.level, func.count(Risk.id)).group_by(Risk.level).all()
    level_dist = {_LEVEL_LABEL.get(lv, lv): cnt for lv, cnt in level_rows}

    # 风险类别 Top（降序）
    cat_rows = db.query(Risk.category, func.count(Risk.id)).group_by(Risk.category).order_by(func.count(Risk.id).desc()).all()
    category_dist = [{"category": cat, "count": cnt} for cat, cnt in cat_rows]

    # 合同状态分布
    cstatus_rows = db.query(Contract.status, func.count(Contract.id)).group_by(Contract.status).all()
    contract_status = {st: cnt for st, cnt in cstatus_rows}

    # 复核状态分布
    rstatus_rows = db.query(Risk.review_status, func.count(Risk.id)).group_by(Risk.review_status).all()
    review_status = {_STATUS_LABEL.get(st, st): cnt for st, cnt in rstatus_rows}

    # 智能体维度分布（多智能体协同：法务/财务各查出多少风险）
    agent_rows = db.query(Risk.agent, func.count(Risk.id)).group_by(Risk.agent).all()
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
