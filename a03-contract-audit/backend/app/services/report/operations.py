"""基于同一授权快照计算当前运营指标，不推断金额、历史或条件日期。"""
from datetime import date


def operational_summary(snapshot: dict, *, today: date | None = None) -> dict:
    today = today or date.today()
    contracts, risks = snapshot["contracts"], snapshot["risks"]
    departments = []
    for name in sorted({c["department"] or "未分类" for c in contracts}):
        rows = [c for c in contracts if (c["department"] or "未分类") == name]
        high_ids = sorted({c["id"] for c in rows if c["risk_high"] > 0})
        departments.append({"department": name, "contract_count": len(rows),
                            "risk_count": sum(c["risk_total"] for c in rows),
                            "high_risk_contracts": len(high_ids), "high_risk_rate": len(high_ids) / len(rows),
                            "contract_ids": [c["id"] for c in rows], "high_risk_contract_ids": high_ids})
    overdue, unknown_due = [], 0
    for task in snapshot["rectifications"]:
        if task["status"] == "已闭环":
            continue
        try:
            due = date.fromisoformat(task["due"])
        except (ValueError, TypeError):
            unknown_due += 1
            continue
        if due < today:
            overdue.append({**task, "overdue_days": (today - due).days})
    return {"metric_version": "operations-v1", "as_of_date": today.isoformat(),
            "high_risk_contracts": sum(c["risk_high"] > 0 for c in contracts),
            "pending_risk_count": sum(r["review_status"] in {"pending", "to_modify"} for r in risks),
            "overdue_count": len(overdue), "unknown_due_count": unknown_due,
            "overdue_actions": sorted(overdue, key=lambda task: (-task["overdue_days"], task["id"])),
            "departments": departments, "historical_state": "INSUFFICIENT_HISTORY",
            "amount_state": "UNVERIFIED", "amount_note": "合同金额尚未完成币种、基数和来源确认，暂不汇总为风险敞口。",
            "risk_count_basis": "当前审查风险记录；跨 Agent 问题尚未完成人工归并，不等于主风险数。"}
