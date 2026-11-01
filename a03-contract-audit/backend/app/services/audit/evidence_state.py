"""API、报告和追问共用的当前证据状态门禁。"""
import json
from collections.abc import Mapping

from app.services.audit.evidence_validation import DETERMINISTIC_SUPPORT_VERSION, SUPPORT_V3_VERSION

CURRENT_SUPPORT_VERSIONS = frozenset({SUPPORT_V3_VERSION, DETERMINISTIC_SUPPORT_VERSION})


def _value(risk, key, default=None):
    return risk.get(key, default) if isinstance(risk, Mapping) else getattr(risk, key, default)


def trace_object(value) -> dict:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            return {}
    return value if isinstance(value, dict) else {}


def evidence_validation_mode(trace) -> str:
    validation = trace_object(trace).get("evidence_validation")
    if isinstance(validation, dict) and validation.get("mode") in {"manual_only", "deterministic", "semantic"}:
        return validation["mode"]
    return "manual_only"


def evidence_list(risk, key, json_key=None) -> list:
    value = _value(risk, key, _value(risk, json_key or key))
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            return []
    return value if isinstance(value, list) else []


def is_current_evidence_verified(risk) -> bool:
    """人工状态独立于机器状态；旧版本和不完整来源不计为已核验。"""
    if (_value(risk, "evidence_status") != "supported"
            or _value(risk, "support_relation_status") != "supported"
            or _value(risk, "support_validator_version") not in CURRENT_SUPPORT_VERSIONS
            or _value(risk, "support_validation_failed_stage") != "none"
            or _value(risk, "support_validation_reason_code") != "EVIDENCE_SUPPORTS_CLAIM"
            or not str(_value(risk, "original_text") or "").strip()
            or _value(risk, "original_text_verified") is not True):
        return False
    sources = evidence_list(risk, "rag_sources")
    ids = evidence_list(risk, "evidence_ids", "evidence_ids_json")
    return (bool(sources) and bool(ids) and len(ids) == len(sources)
            and all(isinstance(value, str) and value.strip() for value in ids)
            and all(isinstance(source, dict) and source.get("reliable") is True
                    and source.get("applicability_status") == "applicable"
                    and str(source.get("source") or "").strip()
                    and str(source.get("content") or "").strip() for source in sources))
