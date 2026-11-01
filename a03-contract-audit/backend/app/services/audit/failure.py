"""统一审查失败的安全文案、历史读取与可恢复性判定。"""
from dataclasses import dataclass
from collections.abc import Mapping

from app.services.audit.result_snapshot import parse_result_snapshot


QUALITY_REASON_MESSAGES = {
    "INCOMPLETE_COVERAGE": "审查覆盖不完整",
    "OUTPUT_TRUNCATED": "模型输出被截断",
    "INVALID_MODEL_OUTPUT": "模型输出格式无效",
    "MODEL_TIMEOUT": "模型调用超时",
    "MODEL_UNAVAILABLE": "模型服务不可用",
    "MODEL_REJECTED": "模型供应商拒绝了审查请求",
    "MODEL_DISABLED": "当前配置已禁用模型，尚未完成模型审查",
    "MODEL_OUTBOUND_BLOCKED": "模型调用被数据出站策略阻止",
    "PAGINATION_EXHAUSTED": "模型分页审查未完成",
    "EVIDENCE_UNRESOLVED": "风险依据尚未核验",
    "ORIGINAL_TEXT_UNRESOLVED": "风险原文尚未核验",
    "PARSE_QUALITY_LOW": "文档解析质量不足，需人工复核",
    "CONTRACT_TEXT_INCOMPLETE": "合同文本不完整，需人工复核",
    "SECONDARY_REVIEW_CONFLICT": "二次复核存在冲突",
    "SECONDARY_REVIEW_PENDING": "二次复核尚未完成",
    "UNBOUND_CONFLICT": "冲突项无法关联到具体风险，需人工复核",
    "AUDIT_DEADLINE_EXCEEDED": "审查达到整体时限，需人工复核",
    "AUDIT_BUDGET_EXHAUSTED": "整单审查调用或令牌预算已用尽，需人工复核",
    "DIMENSION_MISMATCH": "模型返回了本次范围外的风险",
    "FACT_VALIDATION_FAILED": "候选风险的结构化事实校验失败",
}
_ERROR_MESSAGES = QUALITY_REASON_MESSAGES | {
    "AUDIT_PERSISTENCE_UNAVAILABLE": "审查数据存储暂时不可用",
    "STALE_AUDIT_RUN": "审查任务已被更新的运行取代",
    "AUDIT_INTERNAL_ERROR": "审查未能生成完整可靠结果",
}
_RETRYABLE = frozenset({
    "MODEL_TIMEOUT", "MODEL_UNAVAILABLE", "AUDIT_PERSISTENCE_UNAVAILABLE",
    "OUTPUT_TRUNCATED", "INVALID_MODEL_OUTPUT", "PAGINATION_EXHAUSTED",
    "AUDIT_DEADLINE_EXCEEDED",
})
_SERVICE_CODES = (
    "AUDIT_BUDGET_EXHAUSTED",
    "MODEL_DISABLED", "MODEL_OUTBOUND_BLOCKED",
    "MODEL_TIMEOUT", "MODEL_UNAVAILABLE", "AUDIT_PERSISTENCE_UNAVAILABLE",
    "MODEL_REJECTED", "OUTPUT_TRUNCATED", "INVALID_MODEL_OUTPUT",
    "PAGINATION_EXHAUSTED", "AUDIT_DEADLINE_EXCEEDED",
)


@dataclass(frozen=True)
class AuditFailure:
    code: str
    message: str
    retryable: bool
    action: str


def _get(value: object, name: str, default=None):
    return value.get(name, default) if isinstance(value, Mapping) else getattr(value, name, default)


def audit_failure(item: object) -> AuditFailure | None:
    """仅从任务自己的已知错误码生成公开文案，不信任原始异常文本。"""
    if _get(item, "status") not in {"failed", "audit_failed"}:
        return None
    result = parse_result_snapshot(_get(item, "result_json", "{}"))
    codes = []
    issues = result.get("issues")
    if isinstance(issues, list):
        codes.extend(issue.get("code") for issue in issues if isinstance(issue, dict))
    reasons = result.get("quality_reasons")
    if isinstance(reasons, list):
        codes.extend(reasons)
    codes = list(dict.fromkeys(code for code in codes if isinstance(code, str) and code in _ERROR_MESSAGES))
    explicit = _get(item, "error_code")
    if explicit:
        primary = explicit if isinstance(explicit, str) and explicit in _ERROR_MESSAGES else "AUDIT_INTERNAL_ERROR"
    else:
        if not codes:
            reason = result.get("review_reason")
            if isinstance(reason, str):
                codes = [code for code, message in QUALITY_REASON_MESSAGES.items() if message in reason]
        primary = next((code for code in _SERVICE_CODES if code in codes),
                       next(iter(codes), "AUDIT_INTERNAL_ERROR"))
    ordered = list(dict.fromkeys([primary, *codes]))
    message = "；".join(_ERROR_MESSAGES[code] for code in ordered)
    retryable = primary in _RETRYABLE
    if primary == "MODEL_DISABLED":
        action = "请联系管理员启用模型并检查配置后重新审查，当前结果需人工核对"
    elif primary == "AUDIT_BUDGET_EXHAUSTED":
        action = "请交由人工复核；如需重新审查，请联系管理员核对调用与令牌预算后再提交"
    elif primary == "MODEL_OUTBOUND_BLOCKED":
        action = "请联系管理员检查出站策略中的模型地址授权及敏感字段脱敏；处理后从待审合同重新提交，或使用私有模型审查"
    elif primary == "MODEL_REJECTED":
        action = "请联系管理员检查模型凭据、额度或服务策略后再提交审查"
    elif primary in {"PARSE_QUALITY_LOW", "CONTRACT_TEXT_INCOMPLETE"}:
        action = "请人工核对原文件，修正文件后重新解析"
    elif primary in {"AUDIT_INTERNAL_ERROR", "STALE_AUDIT_RUN"}:
        action = "请联系管理员并提供批次号和任务号"
    elif retryable:
        action = "请检查模型服务状态后重试；若重复失败，请联系管理员"
    else:
        action = "请交由法务或财务人员人工核对，不要直接采信未核验结论"
    return AuditFailure(primary, message, retryable, action)
