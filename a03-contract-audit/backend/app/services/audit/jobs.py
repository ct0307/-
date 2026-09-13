"""持久审查任务的创建、幂等与状态读取。"""
from dataclasses import dataclass
import hashlib
import json

from sqlalchemy import exists
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.models import AuditBatch, AuditBatchItem, Contract, User
from app.services import audit_log
from app.services.batch.service import ACTIVE_AUDIT_ITEM_STATUSES


class AuditJobConflict(ValueError):
    """幂等键已用于不同审查请求。"""


@dataclass(frozen=True)
class AuditJobCreation:
    batch: AuditBatch
    item: AuditBatchItem
    created: bool


def normalize_dimensions(dimensions: list[str] | None) -> list[str]:
    return sorted({value.strip() for value in dimensions or [] if value.strip()})


def request_fingerprint(
    *, contract_id: int, contract_type: str, dimensions: list[str] | None
) -> str:
    payload = {
        "contract_id": contract_id,
        "contract_type": contract_type.strip(),
        "dimensions": normalize_dimensions(dimensions),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def import_batch_request_fingerprint(
    *, import_items: list[tuple[int, str]], dimensions: list[str] | None
) -> str:
    payload = {
        "import_items": [
            {"id": item_id, "contract_type": contract_type.strip()}
            for item_id, contract_type in sorted(import_items)
        ],
        "dimensions": normalize_dimensions(dimensions),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def claim_contract_for_audit(
    db: Session,
    *,
    contract_id: int,
    contract_type: str | None = None,
    allow_active: bool = False,
) -> Contract | None:
    """以 Contract 条件更新作为创建审查与删除草稿的共同互斥点。"""
    active_job = exists().where(
        AuditBatchItem.contract_id == Contract.id,
        AuditBatchItem.status.in_(ACTIVE_AUDIT_ITEM_STATUSES),
    )
    values: dict = {
        Contract.audit_generation: Contract.audit_generation + 1,
        Contract.status: "reviewing",
    }
    if contract_type is not None:
        values[Contract.contract_type] = contract_type.strip()
    conditions = [Contract.id == contract_id, Contract.deleted_at.is_(None)]
    if not allow_active:
        conditions.extend(
            [
                Contract.status.notin_(ACTIVE_AUDIT_ITEM_STATUSES),
                ~active_job,
            ]
        )
    claimed = db.query(Contract).filter(*conditions).update(
        values,
        synchronize_session=False,
    )
    if claimed != 1:
        return None
    return (
        db.query(Contract)
        .filter(Contract.id == contract_id)
        .populate_existing()
        .one()
    )


def _existing_job(
    db: Session,
    *,
    owner_id: int,
    idempotency_key: str,
    fingerprint: str,
) -> AuditJobCreation | None:
    batch = db.query(AuditBatch).filter(
        AuditBatch.owner_id == owner_id,
        AuditBatch.idempotency_key == idempotency_key,
    ).first()
    if not batch:
        return None
    if batch.request_fingerprint != fingerprint:
        raise AuditJobConflict("审查幂等键已用于不同请求")
    if len(batch.items) != 1:
        raise AuditJobConflict("审查幂等键指向的任务结构异常")
    return AuditJobCreation(batch=batch, item=batch.items[0], created=False)


def create_single_audit_job(
    db: Session,
    *,
    contract: Contract,
    user: User,
    idempotency_key: str,
    contract_type: str,
    dimensions: list[str] | None,
) -> AuditJobCreation:
    """创建单项持久任务；相同请求返回原任务，不重复派发。"""
    key = idempotency_key.strip()
    if not 8 <= len(key) <= 128:
        raise ValueError("Idempotency-Key 长度必须为 8 至 128")
    normalized_dimensions = normalize_dimensions(dimensions)
    fingerprint = request_fingerprint(
        contract_id=contract.id,
        contract_type=contract_type,
        dimensions=normalized_dimensions,
    )
    existing = _existing_job(
        db,
        owner_id=user.id,
        idempotency_key=key,
        fingerprint=fingerprint,
    )
    if existing:
        return existing

    claimed_contract = claim_contract_for_audit(
        db,
        contract_id=contract.id,
        contract_type=contract_type,
        allow_active=True,
    )
    if claimed_contract is None:
        db.rollback()
        raise AuditJobConflict("合同已删除或不存在")
    generation = claimed_contract.audit_generation

    batch = AuditBatch(
        owner_id=user.id,
        department=user.department,
        idempotency_key=key,
        request_fingerprint=fingerprint,
        dimensions_json=json.dumps(normalized_dimensions, ensure_ascii=False),
        status="queued",
        total=1,
    )
    item = AuditBatchItem(
        contract=claimed_contract,
        filename=claimed_contract.filename,
        status="queued",
        audit_generation=generation,
    )
    batch.items.append(item)
    db.add(batch)
    try:
        db.flush()
        audit_log.record(
            db,
            user_id=user.id,
            action="audit_enqueue",
            target=f"contract:{contract.id}",
            detail=f"job:{item.id},batch:{batch.id}",
        )
        db.commit()
        db.refresh(batch)
        db.refresh(item)
        return AuditJobCreation(batch=batch, item=item, created=True)
    except IntegrityError:
        db.rollback()
        concurrent = _existing_job(
            db,
            owner_id=user.id,
            idempotency_key=key,
            fingerprint=fingerprint,
        )
        if concurrent:
            return concurrent
        raise
