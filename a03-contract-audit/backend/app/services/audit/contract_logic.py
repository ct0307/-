"""合同跨条款逻辑检查与确定性财务计算。"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re

from app.services.rag.contract_structure import build_contract_chunks


_PAYMENT_TERMS = ("付款", "支付", "结算", "付清")
_TRIGGERS = ("验收合格", "验收", "合同签订", "签订", "交付", "开票")
_DURATION_RE = re.compile(
    r"(?P<value>\d+(?:\.\d+)?|[一二三四五六七八九十百]+)\s*"
    r"(?P<unit>个?工作日|日|天|个月|月)"
)
_PERCENT_RE = re.compile(r"(?<!\d)(\d+(?:\.\d+)?)\s*[%％]")


@dataclass(frozen=True)
class ClauseConflict:
    category: str
    trigger: str
    clause_ids: tuple[str, ...]
    values: tuple[str, ...]
    explanation: str


@dataclass(frozen=True)
class PaymentScheduleCheck:
    status: str
    total_percentage: Decimal | None
    clause_ids: tuple[str, ...]
    calculation: str


def detect_clause_conflicts(text: str) -> list[ClauseConflict]:
    """发现同一付款触发条件对应多个不同期限的候选矛盾。"""
    grouped: dict[str, list[tuple[str, str]]] = {}
    for chunk in build_contract_chunks(text):
        if not any(term in chunk.text for term in _PAYMENT_TERMS):
            continue
        trigger = next((value for value in _TRIGGERS if value in chunk.text), "")
        duration = _DURATION_RE.search(chunk.text)
        if not trigger or duration is None:
            continue
        value = f"{duration.group('value')}{duration.group('unit').removeprefix('个')}"
        grouped.setdefault(trigger, []).append((chunk.clause_id, value))

    conflicts: list[ClauseConflict] = []
    for trigger, facts in grouped.items():
        values = tuple(dict.fromkeys(value for _clause_id, value in facts))
        if len(values) < 2:
            continue
        clause_ids = tuple(dict.fromkeys(clause_id for clause_id, _value in facts))
        conflicts.append(ClauseConflict(
            category="付款期限冲突",
            trigger=trigger,
            clause_ids=clause_ids,
            values=values,
            explanation=(
                f"同一触发条件“{trigger}”对应多个付款期限：{'、'.join(values)}，"
                "需结合条款适用范围人工确认是否冲突。"
            ),
        ))
    return conflicts


def analyze_payment_schedule(text: str) -> PaymentScheduleCheck:
    """汇总付款条款中的阶段比例，避免由模型执行基础算术。"""
    percentages: list[Decimal] = []
    clause_ids: list[str] = []
    for chunk in build_contract_chunks(text):
        if not any(term in chunk.text for term in _PAYMENT_TERMS):
            continue
        if "违约金" in chunk.text and not any(term in chunk.text for term in ("预付款", "进度款", "尾款")):
            continue
        values = [Decimal(value) for value in _PERCENT_RE.findall(chunk.text)]
        if not values:
            continue
        percentages.extend(values)
        clause_ids.append(chunk.clause_id)
    if not percentages:
        return PaymentScheduleCheck("not_applicable", None, (), "未检出阶段付款比例")
    total = sum(percentages, Decimal("0"))
    status = "balanced" if total == Decimal("100") else "incomplete" if total < 100 else "excessive"
    expression = " + ".join(f"{value.normalize()}%" for value in percentages)
    return PaymentScheduleCheck(
        status=status,
        total_percentage=total,
        clause_ids=tuple(dict.fromkeys(clause_ids)),
        calculation=f"{expression} = {total.normalize()}%",
    )


def calculate_penalty(
    base_amount: str | Decimal,
    daily_rate: str | Decimal,
    days: int,
    *,
    cap_rate: str | Decimal | None = None,
) -> Decimal:
    """按本金、日费率和逾期天数计算违约金，并应用可选比例上限。"""
    if days < 0:
        raise ValueError("逾期天数不能为负数")
    try:
        amount = Decimal(str(base_amount))
        rate = Decimal(str(daily_rate))
        cap = Decimal(str(cap_rate)) if cap_rate is not None else None
    except InvalidOperation as exc:
        raise ValueError("金额或费率格式无效") from exc
    if amount < 0 or rate < 0 or (cap is not None and cap < 0):
        raise ValueError("金额或费率不能为负数")
    result = amount * rate * days
    if cap is not None:
        result = min(result, amount * cap)
    return result.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def build_logic_cross_checks(text: str) -> list[dict]:
    """转换为现有双 Agent 协作页可直接消费的检查结果。"""
    checks = [
        {
            "id": f"LC-{index}",
            "from": "system",
            "to": "legal",
            "trigger": conflict.explanation,
            "action": "请法务 Agent 对照两个条款的适用范围并给出消歧建议",
            "verdict": "conflict",
            "note": conflict.explanation,
            "category": conflict.category,
            "evidence_clause_ids": list(conflict.clause_ids),
            "values": list(conflict.values),
        }
        for index, conflict in enumerate(detect_clause_conflicts(text), start=1)
    ]
    schedule = analyze_payment_schedule(text)
    if schedule.status in {"incomplete", "excessive"}:
        checks.append({
            "id": "FC-1",
            "from": "system",
            "to": "finance",
            "trigger": f"付款比例合计为 {schedule.total_percentage}%",
            "action": "请财务 Agent 核对付款阶段、含税口径及尾差",
            "verdict": "conflict",
            "note": schedule.calculation,
            "category": "付款比例异常",
            "evidence_clause_ids": list(schedule.clause_ids),
            "values": [str(schedule.total_percentage)],
        })
    return checks
