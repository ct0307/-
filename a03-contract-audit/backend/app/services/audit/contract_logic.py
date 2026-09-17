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


@dataclass(frozen=True)
class FactValidationResult:
    valid: bool
    reason: str = ""


_DIMENSION_KEYWORDS: dict[str, tuple[str, ...]] = {
    "legal": ("主体", "资格", "效力", "授权", "签章", "权利义务"),
    "risk": ("合规", "权责", "关联交易", "关联方", "税", "舞弊"),
    "payment": ("付款", "支付", "金额", "价款", "币种", "发票", "结算", "收款", "账户", "现金流", "大写", "小写"),
    "breach": ("违约", "赔偿", "责任", "违约金"),
    "ip": ("知识产权", "著作权", "专利", "商标"),
    "confidentiality": ("保密", "数据安全", "隐私"),
    "termination": ("终止", "解除", "期限", "履约", "生效", "签订日期", "签署日期", "交付", "验收"),
    "dispute": ("争议", "仲裁", "诉讼", "管辖"),
}

_DATE_RE = re.compile(r"\d{4}\s*[年/-]\s*\d{1,2}\s*[月/-]\s*\d{1,2}\s*日?")
_ARABIC_MONEY_RE = re.compile(r"(?<!\d)(\d[\d,]*(?:\.\d+)?)\s*(万元|元)")
_UPPER_MONEY_RE = re.compile(r"(?:人民币)?([零壹贰叁肆伍陆柒捌玖拾佰仟万亿]+)元(?:整)?")
_UPPER_DIGITS = {"零": 0, "壹": 1, "贰": 2, "叁": 3, "肆": 4, "伍": 5, "陆": 6, "柒": 7, "捌": 8, "玖": 9}
_UPPER_SMALL_UNITS = {"拾": 10, "佰": 100, "仟": 1000}


def candidate_dimensions(risk: dict) -> set[str]:
    """从候选可见文本确定归属维度；不把泛化的“风险”当作任意维度。"""
    category = str(risk.get("category", ""))
    detected = {
        dimension
        for dimension, keywords in _DIMENSION_KEYWORDS.items()
        if any(keyword in category for keyword in keywords)
    }
    if detected:
        return detected
    context = " ".join(str(risk.get(field, "")) for field in (
        "original_text", "risk_reason", "suggestion",
    ))
    return {
        dimension
        for dimension, keywords in _DIMENSION_KEYWORDS.items()
        if any(keyword in context for keyword in keywords)
    }


def validate_candidate_facts(risk: dict, contract_text: str) -> FactValidationResult:
    """仅核验可确定的日期、金额字面量与大小写金额一致性。"""
    reason = str(risk.get("risk_reason", ""))
    original = str(risk.get("original_text", ""))
    contract_dates = {_normalize_date(value) for value in _DATE_RE.findall(contract_text)}
    for value in _DATE_RE.findall(reason):
        if _normalize_date(value) not in contract_dates:
            return FactValidationResult(False, "风险原因包含合同中不存在的日期")

    contract_amounts = set(_arabic_amounts(contract_text))
    for value in _arabic_amounts(reason):
        if value not in contract_amounts:
            return FactValidationResult(False, "风险原因包含合同中不存在的金额")

    mismatch_claimed = any(token in f"{risk.get('category', '')}{reason}" for token in (
        "不一致", "不相符", "不符",
    ))
    if mismatch_claimed:
        arabic = _arabic_amounts(original)
        uppercase = _uppercase_amounts(original)
        if arabic and uppercase and set(arabic).intersection(uppercase):
            return FactValidationResult(False, "合同金额大小写实际一致")
    return FactValidationResult(True)


def _normalize_date(value: str) -> str:
    parts = re.findall(r"\d+", value)
    return "-".join((parts[0], parts[1].zfill(2), parts[2].zfill(2)))


def _arabic_amounts(text: str) -> list[Decimal]:
    values: list[Decimal] = []
    for raw, unit in _ARABIC_MONEY_RE.findall(text):
        value = Decimal(raw.replace(",", ""))
        values.append(value * (Decimal("10000") if unit == "万元" else Decimal("1")))
    return values


def _uppercase_amounts(text: str) -> list[Decimal]:
    return [Decimal(_parse_upper_integer(raw)) for raw in _UPPER_MONEY_RE.findall(text)]


def _parse_upper_integer(value: str) -> int:
    total = section = number = 0
    for char in value:
        if char in _UPPER_DIGITS:
            number = _UPPER_DIGITS[char]
        elif char in _UPPER_SMALL_UNITS:
            section += (number or 1) * _UPPER_SMALL_UNITS[char]
            number = 0
        elif char == "万":
            total += (section + number) * 10_000
            section = number = 0
        elif char == "亿":
            total = (total + section + number) * 100_000_000
            section = number = 0
    return total + section + number


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
    """只有明确同基数且没有重复、累计或选择条件时才求和。"""
    from app.services.report.payment_insights import analyze_payments
    result = analyze_payments(text)
    total = result["total_percentage"]
    return PaymentScheduleCheck(
        status=result["status"],
        total_percentage=Decimal(total) if total is not None else None,
        clause_ids=tuple(dict.fromkeys(e["clause_id"] for e in result["events"] if e["percentage"])),
        calculation=result["calculation"],
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
