"""付款节点的保守规则分析：只有明确同基数时才执行比例求和。"""
import re
from decimal import Decimal

from app.services.rag.contract_structure import build_contract_chunks

_PERCENT = re.compile(r"(?<![\d.])(\d+(?:\.\d+)?)\s*[%％]")
_BASE = re.compile(r"合同(?:总价款|总价|总金额|总额|金额)")
_AMBIGUOUS = re.compile(r"累计|已付|剩余|余额|另行|或者|或支付|也可|任选|若|如果|每批|每月|每期|税率|违约金|不低于|不超过|最多|至少|上限|下限")


def analyze_payments(text: str) -> dict:
    events, issues = [], []
    seen, ambiguous = set(), False
    for chunk in build_contract_chunks(text):
        for sentence in re.split(r"[。；;\n]+", chunk.text):
            quote = sentence.strip()
            if not quote or not re.search(r"支付|付款|付清|结算", quote):
                continue
            percentages = _PERCENT.findall(quote)
            normalized = re.sub(r"\s|^第[一二三四五六七八九十\d]+条", "", quote)
            ambiguous |= normalized in seen or bool(_AMBIGUOUS.search(quote)) or len(percentages) > 1
            seen.add(normalized)
            base = "合同总价" if _BASE.search(quote) else "基数未明确"
            if percentages and base != "合同总价":
                ambiguous = True
            condition = next((v for v in ("未验收", "验收合格", "验收", "交付", "签订", "开票") if v in quote), "条件待确认")
            events.append({"quote": quote, "clause_id": chunk.clause_id, "condition": condition, "percentage": percentages[0] if len(percentages) == 1 else None, "base": base})
    positive = next((e for e in events if "尾款" in e["quote"] and re.search(r"必须.*验收合格|验收合格.*方可|仅.*验收合格", e["quote"])), None)
    negative = next((e for e in events if "尾款" in e["quote"] and re.search(r"未验收.*(?:仍|也|必须).*支付", e["quote"])), None)
    if positive and negative:
        issues.append({"kind": "acceptance_conflict", "message": "尾款的验收前置条件存在候选冲突，需核对适用范围后确认。", "quotes": [positive["quote"], negative["quote"]], "clause_ids": [positive["clause_id"], negative["clause_id"]]})
    values = [Decimal(e["percentage"]) for e in events if e["percentage"] is not None]
    total = None
    if not text.strip():
        status, calculation = "unavailable", "暂无当前代次条款原文，无法分析付款节点。"
    elif ambiguous:
        status, calculation = "needs_review", "存在不同或不明基数、重复、累计或条件比例，未直接相加，请人工确认付款口径。"
    elif not values:
        status, calculation = "not_applicable", "当前条款未检出可计算的付款比例；不能据此推断合同遗漏。"
    else:
        total = sum(values, Decimal("0"))
        status = "balanced" if total == 100 else "excessive" if total > 100 else "incomplete"
        calculation = " + ".join(f"{v:f}%" for v in values) + f" = {total:f}%（明确合同总价基数；仅核对所识别节点）"
        if status != "balanced":
            issues.append({"kind": "percentage", "message": "所识别阶段比例不等于100%，请复核是否存在遗漏、重复或特殊付款安排。", "quotes": [e["quote"] for e in events if e["percentage"]], "clause_ids": [e["clause_id"] for e in events if e["percentage"]]})
    return {"status": status, "total_percentage": f"{total:f}" if total is not None else None, "calculation": calculation, "events": events, "issues": issues}
