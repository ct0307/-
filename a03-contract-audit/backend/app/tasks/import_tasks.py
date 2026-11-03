"""合同导入解析任务。"""

import json
from datetime import datetime, timezone

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import SessionLocal
from app.models.models import ImportBatchItem, LookupItem
from app.services.audit.runner import apply_parse_quality
from app.services.imports.classifier import classify_contract_type
from app.services.imports.errors import parse_failure
from app.services.imports.service import summarize_import, target_status
from app.services.imports.type_profiles import load_type_profiles
from app.services.parser.elements import (
    element_evidence_payload,
    extract_element_result,
    legacy_element_values,
    merge_element_review,
)
from app.services.parser.extractor import extract_document
from app.services.parser.cache import save_parse_cache
from app.services.sign_date import merge_confirmed_sign_date
from app.tasks.celery_app import celery_app

log = get_logger("imports")


def refresh_import_batch(batch) -> None:
    summary = summarize_import([item.status for item in batch.items])
    batch.total = summary.total
    batch.ready = summary.ready
    batch.failed = summary.failed
    batch.status = summary.status


@celery_app.task(name="import.parse_item")
def parse_import_item(item_id: int) -> dict:
    with SessionLocal() as db:
        item = db.get(ImportBatchItem, item_id)
        if not item or item.status in {"ready", "awaiting_confirmation", "deleted", "done"}:
            return {"item_id": item_id, "status": "unchanged"}
        item.status = "parsing"
        item.attempts += 1
        db.commit()
        try:
            if item.contract is None:
                raise ValueError("合同记录不存在")
            parsed = extract_document(item.contract.storage_path)
            apply_parse_quality(item.contract, parsed)
            if item.contract.content_sha256:
                save_parse_cache(db, item.contract, parsed)
            element_result = extract_element_result(parsed)
            elements = legacy_element_values(element_result.values, text=parsed.text)
            merge_confirmed_sign_date(elements, item.contract.elements_json, item.contract.content_sha256)
            evidence_payload = element_evidence_payload(element_result, parsed=parsed)
            requires_review, review_reason = merge_element_review(parsed, element_result)
            item.contract.requires_review = requires_review
            item.contract.review_reason = review_reason
            available = [
                row.value
                for row in db.query(LookupItem)
                .filter(LookupItem.category == "contract_type")
                .order_by(LookupItem.sort_order, LookupItem.id)
                .all()
            ]
            suggestion = classify_contract_type(
                filename=item.filename,
                text=parsed.text,
                available_types=available,
                profiles=load_type_profiles(db, available),
            )
            item.contract.elements_json = json.dumps(elements, ensure_ascii=False)
            item.contract.element_evidence_json = json.dumps(
                evidence_payload,
                ensure_ascii=False,
            )
            item.contract.suggested_type = suggestion.suggested_type
            item.contract.type_confidence = suggestion.confidence
            item.contract.type_evidence_json = json.dumps(suggestion.evidence, ensure_ascii=False)
            item.contract.contract_type = (
                suggestion.suggested_type
                if suggestion.confidence >= settings.CONTRACT_TYPE_CONFIRM_THRESHOLD
                else ""
            )
            item.contract.status = "review_required" if requires_review else "parsed"
            item.status = target_status(
                suggestion.suggested_type,
                suggestion.confidence,
                auto_ready_eligible=suggestion.auto_ready_eligible,
                requires_review=requires_review,
            )
            item.error_code = None
            item.error_message = None
        except Exception as exc:
            failure = parse_failure(exc)
            db.rollback()
            item = db.get(ImportBatchItem, item_id)
            if item is None:
                raise RuntimeError("导入项在失败处理期间不存在") from exc
            item.status = "failed"
            item.error_code = failure.code
            item.error_message = failure.message
            if item.contract is not None:
                item.contract.status = "failed"
                item.contract.requires_review = False
                item.contract.ocr_confidence = None
                item.contract.review_reason = failure.message[:255]
                item.contract.elements_json = json.dumps(merge_confirmed_sign_date(
                    {}, item.contract.elements_json, item.contract.content_sha256,
                ), ensure_ascii=False)
                item.contract.element_evidence_json = "{}"
            log.error(
                "import.parse_failed",
                item_id=item.id,
                contract_id=item.contract_id,
                code=failure.code,
                exception_type=type(exc).__name__,
                attempts=item.attempts,
            )
        refresh_import_batch(item.batch)
        db.commit()
        return {"item_id": item.id, "status": item.status}
