"""已知敏感字段识别。不是完整的个人信息识别器，不替代企业出站审批。"""
import re

_PATTERNS = (
    re.compile(r'(?<!\d)(?:\+?86[- ]?)?1[3-9](?:[- ]?\d){9}(?!\d)'),
    re.compile(r'(?<!\d)\d{17}[\dXx](?!\d)'),
    re.compile(r'(?<!\d)\d(?:[- ]?\d){12,18}(?!\d)'),
    re.compile(r'(?<![A-Za-z0-9_.+\-])[A-Za-z0-9_.+\-]{1,64}@[A-Za-z0-9.\-]{1,253}\.[A-Za-z]{2,63}(?![A-Za-z])'),
    re.compile(r'(?:联系人|姓名|联系地址|通讯地址|住所地|开户行|甲方|乙方)\s*[:：]\s*[^\n，,。；;"<>]{2,80}'),
)


def redact_sensitive_text(text: str) -> str:
    for pattern in _PATTERNS:
        text = pattern.sub('[已脱敏]', text)
    return text


def contains_sensitive_data(value: object) -> bool:
    if isinstance(value, str):
        return any(pattern.search(value) for pattern in _PATTERNS)
    if isinstance(value, dict):
        return any(contains_sensitive_data(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(contains_sensitive_data(item) for item in value)
    return False


def redact_sensitive_values(value):
    if isinstance(value, str):
        return redact_sensitive_text(value)
    if isinstance(value, dict):
        return {key: redact_sensitive_values(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_sensitive_values(item) for item in value]
    return value
