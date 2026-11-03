"""人工签订日期与原始文件绑定；重新解析只保留同一文件的确认。"""
import json


def read_elements(raw: str | None) -> dict:
    try:
        value = json.loads(raw or '{}')
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def merge_confirmed_sign_date(elements: dict, previous_json: str | None, content_sha256: str | None) -> dict:
    previous = read_elements(previous_json)
    if (content_sha256 and previous.get('sign_date_confirmed') is True
            and previous.get('sign_date_content_sha256') == content_sha256):
        elements.update({key: value for key, value in previous.items()
                         if key == 'sign_date' or key.startswith('sign_date_')})
    return elements


def sign_date_view(contract) -> dict:
    values = read_elements(contract.elements_json)
    confirmed = bool(contract.content_sha256 and values.get('sign_date_confirmed') is True
                     and values.get('sign_date_content_sha256') == contract.content_sha256)
    return dict(contract_id=contract.id, contract_type=contract.contract_type or '',
                sign_date=values.get('sign_date') or '', confirmed=confirmed,
                confirmed_by=values.get('sign_date_confirmed_by') if confirmed else None,
                confirmed_by_name=values.get('sign_date_confirmed_by_name') if confirmed else None,
                confirmed_at=values.get('sign_date_confirmed_at') if confirmed else None,
                audit_invalidated=bool(values.get('sign_date_invalidated_generation') == contract.audit_generation))
