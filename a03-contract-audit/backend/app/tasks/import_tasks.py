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
from app.services.parser.extractor import extract_document, extract_elements
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
            elements = extract_elements(parsed.text)
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
            )
            item.contract.elements_json = json.dumps(elements, ensure_ascii=False)
            item.contract.suggested_type = suggestion.suggested_type
            item.contract.type_confidence = suggestion.confidence
            item.contract.type_evidence_json = json.dumps(suggestion.evidence, ensure_ascii=False)
            item.contract.contract_type = (
                suggestion.suggested_type
                if suggestion.confidence >= settings.CONTRACT_TYPE_CONFIRM_THRESHOLD
                else ""
            )
            item.contract.status = "parsed"
            item.status = target_status(
                suggestion.suggested_type,
                suggestion.confidence,
                auto_ready_eligible=suggestion.auto_ready_eligible,
                requires_review=parsed.requires_review,
            )
            item.error_code = None
            item.error_message = None
        except Exception as exc:
            failure = parse_failure(exc)
            item.status = "failed"
            item.error_code = failure.code
            item.error_message = failure.message
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
