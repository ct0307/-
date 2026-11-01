"""整改验收报告阅读项；只展示已留存事实，不生成验收决定。"""
import json

from .decision_brief import value_text


def rectification_details(task: dict) -> list[tuple[str, str]]:
    stage = {"unsigned": "未签署", "signed": "已签署", "unknown": "签署阶段待确认"}
    method = {"revision": "草稿修订", "supplement": "补充协议", "performance": "履约措施"}
    rows = [
        ("整改措施", value_text(task.get("note"))),
        ("验收条件", value_text(task.get("acceptance_criteria"))),
        ("合同阶段 / 处理方式", stage.get(task.get("contract_stage"), "待确认") + " / " + method.get(task.get("handling_method"), "待确认")),
        ("整改结果", value_text(task.get("resolution"))),
        ("提交人 / 复核人ID", value_text(task.get("submitted_by"), "未记录") + " / " + value_text(task.get("reviewed_by"), "未记录")),
        ("提交 / 复核时间", value_text(task.get("submitted_at"), "未记录") + " / " + value_text(task.get("reviewed_at"), "未记录")),
        ("复核意见", value_text(task.get("review_comment"))),
    ]
    evidence = task.get("evidence") or []
    rows.append(("整改材料（提交时快照）", "\n".join(
        f"材料 {item.get('contract_id')}：{value_text(item.get('filename'))}；SHA-256：{value_text(item.get('content_sha256'), '未记录')}；{value_text(item.get('description'), '说明未记录')}"
        for item in evidence if isinstance(item, dict)
    ) or "未留存材料，不能视为已验收"))
    if task.get("after_text"):
        rows.append(("修改后条款（人工填写）", value_text(task["after_text"])))
    if task.get("acceptance_reason") or task.get("residual_risk"):
        rows.extend([
            ("风险接受理由", value_text(task.get("acceptance_reason"))),
            ("剩余风险（未消除）", value_text(task.get("residual_risk"))),
            ("风险接受说明", "授权接受不等于整改消除；具体批准状态以实际任务状态为准。"),
        ])
    if task.get("escalation_reason"):
        rows.append(("升级处理记录", value_text(task["escalation_reason"]) + " / " + value_text(task.get("escalated_at"), "时间未记录")))
    for event in task.get("events") or []:
        if not isinstance(event, dict):
            continue
        rows.append(("处理历史", f"{value_text(event.get('occurred_at'))} / {value_text(event.get('actor'))} / {value_text(event.get('action'))} / {value_text(event.get('from_status'))} → {value_text(event.get('to_status'))}\n"
                     + json.dumps(event.get("snapshot") or {}, ensure_ascii=False, sort_keys=True)))
    return rows
