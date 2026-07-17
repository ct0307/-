"""报表导出：Excel 风险台账 + 看板聚合数据。"""
import io
import json

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


def contracts_metadata(db: Session) -> list[dict]:
    """合同要素汇总：每份合同的甲方/标的/收付款节点 + 风险统计，供多维报表展示。"""
    contracts = db.query(Contract).order_by(Contract.id.desc()).all()
    result = []
    for c in contracts:
        elems = {}
        try:
            elems = json.loads(c.elements_json or "{}")
        except (ValueError, AttributeError):
            pass
        risk_rows = db.query(Risk.level, func.count(Risk.id)).filter(
            Risk.contract_id == c.id
        ).group_by(Risk.level).all()
        risk_counts = {lv: cnt for lv, cnt in risk_rows}
        result.append({
            "id": c.id,
            "filename": c.filename,
            "contract_type": c.contract_type or "—",
            "department": c.department or "—",
            "party_a": elems.get("party_a") or "—",
            "subject": elems.get("subject") or "—",
            "payment_terms": (elems.get("payment_terms") or "—")[:80],  # 截断防超宽
            "amount": elems.get("amount") or "—",
            "risk_high": risk_counts.get("high", 0),
            "risk_medium": risk_counts.get("medium", 0),
            "risk_low": risk_counts.get("low", 0),
            "risk_total": sum(risk_counts.values()),
            "status": c.status,
        })
    return result


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
    全部来自真实聚合：KPI/风险分布/部门/Top 为全量统计；趋势按合同 created_at
    逐日累计（合同级口径，与 KPI 一致），数据点数 = 有合同产生的自然日数，
    响应以 mode 标注（real≥2 点 / sparse<2 点）。range_key 保留向后兼容，
    当前趋势为全量累计、不随分段变化（数据跨度不足时分段无意义）。
    """
    range_key = range_key if range_key in _RANGE_LABELS else "month"

    total_contracts = db.query(func.count(Contract.id)).scalar() or 0
    total_risks = db.query(func.count(Risk.id)).scalar() or 0

    # 风险等级分布（用于 donut + KPI 高风险数）
    level_rows = dict(db.query(Risk.level, func.count(Risk.id)).group_by(Risk.level).all())
    high = level_rows.get("high", 0)
    medium = level_rows.get("medium", 0)
    low = level_rows.get("low", 0)

    # 合规通过率：无「高风险」合同占比（口径统一——合同下无 high 级风险即视为通过）
    high_risk_contract_ids = {
        cid for (cid,) in db.query(Risk.contract_id).filter(Risk.level == "high").distinct().all()
    }
    passed = total_contracts - len(high_risk_contract_ids)
    pass_rate = round(passed / total_contracts * 100, 1) if total_contracts else 0.0

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

    # 趋势：按合同真实 created_at 逐日累计（合同级口径，与 KPI 一致）。
    # total=累计审查合同数，risk=累计含高风险合同数，pass=累计通过（无高风险）合同数。
    # 数据点数 = 有合同产生的自然日数；<2 天时 mode=sparse，前端提示"数据积累中"。
    labels, total_series, pass_series, risk_series = _cumulative_trend(db, high_risk_contract_ids)
    mode = "real" if len(labels) >= 2 else "sparse"

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
        ],
        "depts": depts,
        "tops": tops,
        "mode": mode,
    }


def _cumulative_trend(db: Session, high_risk_contract_ids: set) -> tuple[list, list, list, list]:
    """按合同 created_at 的自然日聚合，返回 (日期标签, 累计合同数, 累计通过数, 累计高风险数)。

    真实时间序列：每个数据点对应一个有合同产生的日期，数值为截至当日的累计量。
    数据稀疏（合同集中在少数几天）时点数就少，是真实反映而非编造。
    """
    rows = db.query(Contract.id, Contract.created_at).order_by(Contract.created_at).all()
    # 按日期分桶：{date_str: [该日合同数, 该日高风险合同数]}
    buckets: dict[str, list[int]] = {}
    for cid, created in rows:
        if created is None:
            continue
        day = created.strftime("%m-%d")
        b = buckets.setdefault(day, [0, 0])
        b[0] += 1
        if cid in high_risk_contract_ids:
            b[1] += 1

    labels: list[str] = []
    total_series: list[int] = []
    pass_series: list[int] = []
    risk_series: list[int] = []
    cum_total = cum_risk = 0
    for day in sorted(buckets.keys()):
        cnt, risk_cnt = buckets[day]
        cum_total += cnt
        cum_risk += risk_cnt
        labels.append(day)
        total_series.append(cum_total)
        risk_series.append(cum_risk)
        pass_series.append(cum_total - cum_risk)
    return labels, total_series, pass_series, risk_series
