"""供Excel和Word共用的阅读模型；只整理已有事实，不自动批准合同。"""
import re
from datetime import datetime, timezone, timedelta
from app.services.audit.evidence_state import is_current_evidence_verified

LEVEL = {"high": "高风险", "medium": "中风险", "low": "低风险"}
REVIEW = {"pending": "待复核", "confirmed": "已确认风险", "ignored": "已忽略", "to_modify": "待修改"}


def value_text(value, missing="待补充"):
    if value is None or value == "" or value == "—":
        return missing
    if isinstance(value, (list, tuple)):
        return "；".join(value_text(item) for item in value)
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]", "", str(value))


def excerpt(value, limit=100):
    text = value_text(value, "未提供，待专业人员补充")
    return text if len(text) <= limit else text[:limit] + "…〔节选，完整内容见后续明细〕"


def local_time(value):
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return value_text(value)


def evidence_verified(risk):
    return is_current_evidence_verified(risk)


def validation_text(risk):
    mode = {"deterministic": "有限规则核验", "manual_only": "人工核验", "semantic": "语义核验"}.get(risk.get("support_validation_mode"), "方式未记录")
    return " / ".join([mode, value_text(risk.get("support_validator_version"), "版本未记录"),
                       value_text(risk.get("support_validation_failed_stage"), "阶段未记录"),
                       value_text(risk.get("support_validation_reason_code"), "原因码未记录")])


def human_review_text(risk):
    review = (risk.get("decision_trace") or {}).get("human_review")
    if not isinstance(review, dict):
        return "暂无人工复核记录；人工确认独立于机器证据核验。"
    return f"操作人ID {review.get('operator_id')} / {value_text(review.get('reviewed_at'))} / {REVIEW.get(review.get('status'), '待复核')} / {value_text(review.get('reason'), '已重置为待复核')}"


def contract_facts(contract):
    elements = contract.get("elements") or {}
    return [("合同名称", value_text(contract.get("filename"))),
            ("甲方", value_text(contract.get("party_a") or elements.get("party_a"))),
            ("乙方", value_text(elements.get("party_b"))),
            ("合同标的", value_text(contract.get("subject") or elements.get("subject"))),
            ("金额（原文）", value_text(contract.get("amount") or elements.get("amount"))),
            ("履行期限", value_text(elements.get("duration"))),
            ("付款安排", value_text(contract.get("payment_terms") or elements.get("payment_terms"))),
            ("所属部门 / 类型", value_text(contract.get("department")) + " / " + value_text(contract.get("contract_type")))]


def decision_brief(snapshot):
    risks = sorted(snapshot["risks"], key=lambda r: (
        r.get("review_status") == "ignored",
        {"high": 0, "medium": 1, "low": 2}.get(r.get("level"), 3), r["id"]))
    actions = {}
    for task in snapshot["rectifications"]:
        actions.setdefault(task["risk_id"], []).append(task)
    issues = []
    for risk in risks:
        tasks = actions.get(risk["id"], [])
        issues.append({"risk": risk, "ref": f"R{risk['id']}",
            "level": LEVEL.get(risk.get("level"), value_text(risk.get("level"))),
            "review": REVIEW.get(risk.get("review_status"), "待确认"),
            "verification": "原文与依据已核验" if evidence_verified(risk) else "证据尚未核验完整",
            "owner": "；".join(value_text(t.get("owner"), "待分派") for t in tasks) or "待分派",
            "due": "；".join(value_text(t.get("due"), "待约定") for t in tasks) or "待约定",
            "action_status": "；".join("已接受风险（保留剩余风险）" if t.get("status") == "已接受风险" else value_text(t.get("status"), "待确认") for t in tasks) or "尚未建立整改任务",
            "tasks": tasks})
    s = snapshot["summary"]
    pending = sum(r.get("review_status") not in {"confirmed", "ignored"} for r in risks)
    unverified = sum(not evidence_verified(r) for r in risks)
    missing = sum(any(v == "待补充" for k, v in contract_facts(c) if k in {"甲方", "乙方", "合同标的", "金额（原文）", "履行期限", "付款安排"}) for c in snapshot["contracts"])
    reasons = []
    accepted_count = sum(task.get("status") == "已接受风险" for task in snapshot["rectifications"])
    if accepted_count:
        reasons.append(f"{accepted_count}项风险已经接受但仍保留剩余风险")
    for key, label in [("unreviewed", "份合同尚未审查"), ("running", "份合同仍在处理"), ("failed", "份合同审查失败")]:
        if s.get(key):
            reasons.append(f"{s[key]}{label}")
    if pending:
        reasons.append(f"{pending}条风险待复核或修改")
    if unverified:
        reasons.append(f"{unverified}条风险证据尚未核验完整")
    if s.get("review_required"):
        reasons.append(f"{s['review_required']}份合同处于待人工复核状态")
    if missing:
        reasons.append(f"{missing}份合同关键要素待补充")
    if not s["total"]:
        status, note = "无合同可供评阅", "请确认所选范围和访问权限后重新生成报告。"
    elif reasons:
        status, note = "待补充与专业复核", "；".join(reasons) + "。"
    else:
        status, note = "供授权人员评阅", "当前记录未显示上述材料缺项；是否签署仍由授权审批人员决定。"
    active = [i for i in issues if i["risk"].get("review_status") != "ignored"]
    return {"status": status, "note": note, "issues": issues, "focus": active[:3],
            "focus_remaining": max(0, len(active)-3), "pending": pending,
            "unverified": unverified, "missing_contracts": missing,
            "original_verified": sum(r.get("original_text_verified") is True for r in risks),
            "human_confirmed": sum(r.get("review_status") == "confirmed" for r in risks),
            "unassigned": sum(not i["tasks"] or any(not t.get("owner") or t.get("owner") == "—" for t in i["tasks"]) for i in active),
            "generated": local_time(snapshot["generated_at"])}
