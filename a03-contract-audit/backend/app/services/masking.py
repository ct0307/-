"""字段级脱敏：企业数据安全硬约束。

按调用方角色决定是否对敏感字段脱敏：
- admin / legal / finance：可见全部字段（审查工作需要）
- business：提交人姓名脱敏、风险原文截断

设计原则：
- 脱敏在响应层做，不改数据库存储
- 各端点显式调用，行为可审计
- 脱敏后字段用标记 [已脱敏] 说明，满足"可解释"要求
"""
import json


def is_full_access(role: str) -> bool:
    """admin / legal / finance 拥有完整字段访问权，business 受限。"""
    return role in {"admin", "legal", "finance"}


def mask_name(name: str) -> str:
    """人名脱敏：保留首字，其余替换为星号。

    示例：曾庆豪 → 曾**  /  Alice → A****
    """
    if not name:
        return name
    if len(name) == 1:
        return name[0] + "*"
    return name[0] + "*" * (len(name) - 1)


def mask_original_text(text: str, max_len: int = 80) -> str:
    """合同原文截断脱敏：超过 max_len 时截断并标注已脱敏。

    示例：
      '甲方于收到货物后 90 日内付款，乙方不得拒绝...'（100 字）
      → '甲方于收到货物后 90 日内付款，乙方不得...[已脱敏]'
    """
    if not text or len(text) <= max_len:
        return text
    return text[:max_len] + "…[已脱敏]"


def apply_history_row_masking(row: dict, role: str) -> dict:
    """对审查历史行按角色脱敏。原 dict 不可变，返回新副本。"""
    if is_full_access(role):
        return row
    return {**row, "submitter": mask_name(row.get("submitter", ""))}


def apply_risk_masking(risk: dict | object, role: str) -> dict:
    """对风险条款按角色脱敏。接受 dict 或 ORM 对象（转 dict 处理）。"""
    if is_full_access(role):
        # 完整访问权：原样返回（ORM 对象交给 Pydantic 序列化）
        return risk  # type: ignore[return-value]
    # business 角色：仅截断原文
    if hasattr(risk, "__dict__"):
        # ORM 对象：转为可修改 dict
        d = {
            "id": risk.id,
            "agent": risk.agent,
            "level": risk.level,
            "category": risk.category,
            "original_text": mask_original_text(risk.original_text or ""),
            "basis": risk.basis,
            "suggestion": risk.suggestion,
            "confidence": risk.confidence,
            "tier": risk.tier,
            "review_status": risk.review_status,
            # rag_sources 是公开法条来源、非敏感数据，business 也应可见。
            # DB 里存 JSON 字符串，此处反序列化为 list，与全访问路（RiskOut validator）输出一致。
            "rag_sources": json.loads(risk.rag_sources or "[]"),
        }
    else:
        d = dict(risk)
        d["original_text"] = mask_original_text(d.get("original_text", ""))
    return d
