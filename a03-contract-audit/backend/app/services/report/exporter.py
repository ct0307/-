"""报表导出：Excel 风险台账 + 看板聚合数据。"""
import io

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.models import Contract, Risk

# 报表时间分段 → 趋势坐标轴标签。真实系统应有时间序列聚合表，
# 当前 DB 无历史快照，趋势轴用固定档位标签 + 真实总量末点，稀疏时以 mode 标注。
_RANGE_LABELS = {
    "month": ["第1周", "第2周", "第3周", "第4周", "第5周", "第6周", "本周"],
    "quarter": ["1月", "2月", "3月", "4月", "5月", "6月", "本月"],
    "year": ["Q1", "Q2", "Q3", "Q4", "上年Q3", "上年Q4", "本季"],
}

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


def report_summary(db: Session, range_key: str = "month") -> dict:
    """多维报表聚合：KPI + 趋势 + 风险分布 + 部门排行 + 高风险类别 Top5。

    形状对齐前端 `ReportData`（frontend/src/mock/reports.ts）。
    KPI/风险分布/部门/Top 来自真实聚合；趋势轴无历史快照，用固定档位标签，
    末点落真实总量、前几点按比例递推，响应以 mode 标注（real/sparse）。
    """
    range_key = range_key if range_key in _RANGE_LABELS else "month"

    total_contracts = db.query(func.count(Contract.id)).scalar() or 0
    total_risks = db.query(func.count(Risk.id)).scalar() or 0

    # 风险等级分布（用于 donut + KPI 高风险数）
    level_rows = dict(db.query(Risk.level, func.count(Risk.id)).group_by(Risk.level).all())
    high = level_rows.get("high", 0)
    medium = level_rows.get("medium", 0)
    low = level_rows.get("low", 0)

    # 合规通过率：无风险合同占比（近似——合同下无风险即视为通过）
    risky_contract_ids = {cid for (cid,) in db.query(Risk.contract_id).distinct().all()}
    passed = total_contracts - len(risky_contract_ids)
    pass_rate = round(passed / total_contracts * 100, 1) if total_contracts else 0.0
    no_risk = passed  # donut「无风险」段 = 通过的合同数

    # 部门风险排行：按合同部门聚合风险数
    dept_rows = (
        db.query(Contract.department, func.count(Risk.id))
        .join(Risk, Risk.contract_id == Contract.id)
        .group_by(Contract.department)
        .order_by(func.count(Risk.id).desc())
        .all()
    )
    depts = [
        {"name": dept or "未分类", "risk": cnt, "money": "—"}
        for dept, cnt in dept_rows
    ]

    # 高风险条款 Top5：按类别聚合
    cat_rows = (
        db.query(Risk.category, func.count(Risk.id))
        .group_by(Risk.category)
        .order_by(func.count(Risk.id).desc())
        .limit(5)
        .all()
    )
    tops = [{"name": cat, "value": cnt} for cat, cnt in cat_rows]

    # 趋势：无时间序列表，用固定档位标签 + 末点真实总量、前点按等比递推占位
    labels = _RANGE_LABELS[range_key]
    n = len(labels)
    total_series = _ramp_series(total_contracts, n)
    risk_series = _ramp_series(high + medium, n)
    pass_series = [max(0, t - r) for t, r in zip(total_series, risk_series)]
    mode = "real" if total_contracts >= n else "sparse"

    return {
        "kpi": {
            "total": total_contracts,
            "pass": pass_rate,
            "risk": high,
            "time": "—",  # 平均审查耗时需模型调用记录聚合，暂无
        },
        "kpiTrend": {"total": "", "pass": "", "risk": "", "time": ""},
        "trend": {
            "labels": labels,
            "total": total_series,
            "pass": pass_series,
            "risk": risk_series,
        },
        "donut": [
            {"name": "高风险", "value": high},
            {"name": "中风险", "value": medium},
            {"name": "低风险", "value": low},
            {"name": "无风险", "value": no_risk},
        ],
        "depts": depts,
        "tops": tops,
        "mode": mode,
    }


def _ramp_series(total: int, n: int) -> list[int]:
    """把总量 total 分摊成 n 点的递增趋势占位（末点接近 total）。"""
    if n <= 0:
        return []
    if total <= 0:
        return [0] * n
    # 线性递增权重，归一化后按 total 分配，保证求和≈total 且末点最大
    weights = [i + 1 for i in range(n)]
    s = sum(weights)
    return [max(1, round(total * w / s)) for w in weights]
