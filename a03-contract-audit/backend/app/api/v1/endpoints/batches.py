"""持久化异步审查批次：创建、查询与失败项重试。"""
import json
import os
import uuid
from dataclasses import dataclass

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import require_department_access, require_roles
from app.core.config import settings
from app.core.crypto import encrypt_bytes
from app.core.logging import get_logger
from app.db.session import get_db
from app.models.models import (
    AuditBatch,
    AuditBatchItem,
    AuditLog,
    Contract,
    ImportBatchItem,
    User,
)
from app.schemas.batch import BatchFromImportRequest, BatchOut, BatchRetryOut
from app.services.audit.jobs import import_batch_request_fingerprint, normalize_dimensions
from app.services.batch.service import retry_failed_item, summarize
from app.tasks.dispatcher import dispatch_audit_item

router = APIRouter()
log = get_logger("batches")

_ALLOWED_EXTENSIONS = frozenset({".pdf", ".docx", ".txt"})
_MAX_BATCH_FILES = 200
_MAX_TOTAL_BYTES = 500 * 1024 * 1024


@dataclass(frozen=True)
class _ValidatedUpload:
    filename: str
    extension: str
    content: bytes


def _validate_uploads(files: list[UploadFile]) -> list[_ValidatedUpload]:
    if not files or len(files) > _MAX_BATCH_FILES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "单次必须上传 1 至 200 份合同")

    validated: list[_ValidatedUpload] = []
    total_bytes = 0
    for file in files:
        filename = os.path.basename(file.filename or "unknown")
        extension = os.path.splitext(filename)[1].lower()
        if extension not in _ALLOWED_EXTENSIONS:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"不支持的文件类型: {extension or '无扩展名'}")
        content = file.file.read()
        if not content:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"文件为空: {filename}")
        if len(content) > settings.MAX_UPLOAD_MB * 1024 * 1024:
            raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, f"文件超过大小限制: {filename}")
        total_bytes += len(content)
        if total_bytes > _MAX_TOTAL_BYTES:
            raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "批次总大小超过 500MB")
        validated.append(_ValidatedUpload(filename, extension, content))
    return validated


def _dispatch_item(item: AuditBatchItem, dimensions: list[str]) -> str:
    return dispatch_audit_item(item, dimensions)


def _mark_dispatch_pending(item: AuditBatchItem, exc: Exception) -> None:
    item.status = "queued"
    item.task_id = None
    item.error_code = "DISPATCH_PENDING"
    item.error = "任务已保存，正在等待重新派发"
    log.error(
        "audit.dispatch_pending",
        batch_id=item.batch_id,
        job_id=item.id,
        contract_id=item.contract_id,
        exception_type=type(exc).__name__,
    )


def _refresh_batch(batch: AuditBatch) -> None:
    progress = summarize([item.status for item in batch.items])
    batch.status = progress.status
    batch.total = progress.total
    batch.completed = progress.completed
    batch.failed = progress.failed


def _require_batch_access(batch: AuditBatch, user: User) -> None:
    require_department_access(user, batch.department)


@router.post("", response_model=BatchOut, status_code=status.HTTP_202_ACCEPTED)
def create_batch(
    files: list[UploadFile] = File(...),
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    contract_type: str = Form(""),
    dimensions: list[str] = Form(default=[]),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("legal", "finance", "admin")),
) -> BatchOut:
    """兼容旧调用方的文件上传端点；新界面改用 ``/from-import``。"""
    key = idempotency_key.strip()
    if not 8 <= len(key) <= 128:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Idempotency-Key 长度必须为 8 至 128")

    existing = db.query(AuditBatch).filter(
        AuditBatch.owner_id == user.id,
        AuditBatch.idempotency_key == key,
    ).first()
    if existing:
        return BatchOut.model_validate(existing)

    uploads = _validate_uploads(files)
    confirmed_type = contract_type.strip()
    if not confirmed_type:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "请先确认合同类型")
    os.makedirs(settings.storage_path, exist_ok=True)
    created_paths: list[str] = []
    committed = False
    try:
        batch = AuditBatch(
            owner_id=user.id,
            department=user.department,
            idempotency_key=key,
            dimensions_json=json.dumps(dimensions, ensure_ascii=False),
            total=len(uploads),
        )
        db.add(batch)
        db.flush()

        for upload in uploads:
            stored_path = os.path.join(settings.storage_path, f"{uuid.uuid4().hex}{upload.extension}")
            with open(stored_path, "wb") as stream:
                stream.write(encrypt_bytes(upload.content))
            created_paths.append(stored_path)

            contract = Contract(
                filename=upload.filename,
                storage_path=stored_path,
                contract_type=confirmed_type,
                department=user.department,
                status="uploaded",
                uploaded_by=user.id,
                audit_generation=1,
            )
            db.add(contract)
            db.flush()
            batch.items.append(AuditBatchItem(
                contract_id=contract.id,
                filename=upload.filename,
                status="queued",
                audit_generation=1,
            ))

        db.add(AuditLog(
            user_id=user.id,
            action="batch_create",
            target=f"batch:{batch.id}",
            detail=f"files={len(uploads)},dimensions={','.join(dimensions) or 'all'}",
        ))
        db.commit()
        committed = True
        db.refresh(batch)
    except IntegrityError:
        db.rollback()
        duplicate = db.query(AuditBatch).filter(
            AuditBatch.owner_id == user.id,
            AuditBatch.idempotency_key == key,
        ).first()
        if duplicate:
            for path in created_paths:
                if os.path.isfile(path):
                    os.unlink(path)
            return BatchOut.model_validate(duplicate)
        if not committed:
            _cleanup_created_files(created_paths)
        raise HTTPException(status.HTTP_409_CONFLICT, "批次幂等键冲突")
    except HTTPException:
        db.rollback()
        if not committed:
            _cleanup_created_files(created_paths)
        raise
    except Exception as exc:
        db.rollback()
        if not committed:
            _cleanup_created_files(created_paths)
        detail = (
            "批次已创建，但响应确认失败，请使用原幂等键重试查询"
            if committed
            else "批次创建失败，已回滚"
        )
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail) from exc

    for item in batch.items:
        try:
            item.task_id = _dispatch_item(item, dimensions)
            item.error_code = None
            item.error = None
        except Exception as exc:
            _mark_dispatch_pending(item, exc)
    _refresh_batch(batch)
    db.commit()
    db.refresh(batch)
    return BatchOut.model_validate(batch)


@router.post("/from-import", response_model=BatchOut, status_code=status.HTTP_202_ACCEPTED)
def create_batch_from_import(
    body: BatchFromImportRequest,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("legal", "finance", "admin")),
) -> BatchOut:
    """从已确认的导入项创建审查批次，不复制合同文件。"""
    key = idempotency_key.strip()
    if not 8 <= len(key) <= 128:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Idempotency-Key 长度必须为 8 至 128")
    if len(set(body.import_item_ids)) != len(body.import_item_ids):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "导入项不能重复")

    items = (
        db.query(ImportBatchItem)
        .filter(ImportBatchItem.id.in_(body.import_item_ids))
        .with_for_update()
        .all()
    )
    item_by_id = {item.id: item for item in items}
    if len(item_by_id) != len(body.import_item_ids):
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            {"code": "IMPORT_ITEM_NOT_FOUND", "message": "部分导入项不存在"},
        )
    ordered_items = [item_by_id[item_id] for item_id in body.import_item_ids]
    for item in ordered_items:
        if item.contract is None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                {"code": "IMPORT_ITEM_NOT_READY", "message": "导入项尚未生成合同草稿"},
            )
        require_department_access(user, item.contract.department)

    normalized_dimensions = normalize_dimensions(body.dimensions)
    fingerprint = import_batch_request_fingerprint(
        import_items=[(item.id, item.contract.contract_type) for item in ordered_items],
        dimensions=normalized_dimensions,
    )
    existing = db.query(AuditBatch).filter(
        AuditBatch.owner_id == user.id,
        AuditBatch.idempotency_key == key,
    ).first()
    if existing:
        if existing.request_fingerprint != fingerprint:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                {"code": "IDEMPOTENCY_CONFLICT", "message": "幂等键已用于其他审查请求"},
            )
        return BatchOut.model_validate(existing)

    departments = {item.contract.department for item in ordered_items}
    if len(departments) != 1:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {"code": "MIXED_DEPARTMENTS", "message": "同一审查批次只能包含同一部门合同"},
        )
    for item in ordered_items:
        contract = item.contract
        if (
            item.status != "ready"
            or contract.deleted_at is not None
            or not contract.contract_type.strip()
        ):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                {"code": "IMPORT_ITEM_NOT_READY", "message": f"{item.filename} 尚未就绪"},
            )
        active = db.query(AuditBatchItem.id).filter(
            AuditBatchItem.contract_id == contract.id,
            AuditBatchItem.status.in_(("queued", "parsing", "auditing")),
        ).first()
        if active:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                {"code": "CONTRACT_ALREADY_AUDITING", "message": f"{item.filename} 正在审查"},
            )

    batch = AuditBatch(
        owner_id=user.id,
        department=next(iter(departments)),
        idempotency_key=key,
        request_fingerprint=fingerprint,
        dimensions_json=json.dumps(normalized_dimensions, ensure_ascii=False),
        status="queued",
        total=len(ordered_items),
    )
    for source_item in ordered_items:
        contract = source_item.contract
        contract.audit_generation += 1
        contract.status = "auditing"
        source_item.status = "auditing"
        batch.items.append(AuditBatchItem(
            contract=contract,
            import_item_id=source_item.id,
            filename=source_item.filename,
            status="queued",
            audit_generation=contract.audit_generation,
        ))
    db.add(batch)
    try:
        db.flush()
        db.add(AuditLog(
            user_id=user.id,
            action="batch_create_from_import",
            target=f"batch:{batch.id}",
            detail=f"import_items={','.join(str(item.id) for item in ordered_items)}",
        ))
        db.commit()
        db.refresh(batch)
    except IntegrityError as exc:
        db.rollback()
        concurrent = db.query(AuditBatch).filter(
            AuditBatch.owner_id == user.id,
            AuditBatch.idempotency_key == key,
        ).first()
        if concurrent and concurrent.request_fingerprint == fingerprint:
            return BatchOut.model_validate(concurrent)
        raise HTTPException(status.HTTP_409_CONFLICT, "审查批次幂等键冲突") from exc

    for item in batch.items:
        try:
            item.task_id = _dispatch_item(item, normalized_dimensions)
            item.error_code = None
            item.error = None
        except Exception as exc:
            _mark_dispatch_pending(item, exc)
    _refresh_batch(batch)
    db.commit()
    db.refresh(batch)
    return BatchOut.model_validate(batch)


def _cleanup_created_files(paths: list[str]) -> None:
    for path in paths:
        if os.path.isfile(path):
            os.unlink(path)


@router.get("/{batch_id}", response_model=BatchOut)
def get_batch(
    batch_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("legal", "finance", "admin")),
) -> BatchOut:
    batch = db.query(AuditBatch).filter(AuditBatch.id == batch_id).first()
    if not batch:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "审查批次不存在")
    _require_batch_access(batch, user)
    _refresh_batch(batch)
    db.commit()
    db.refresh(batch)
    return BatchOut.model_validate(batch)


@router.post("/{batch_id}/retry", response_model=BatchRetryOut)
def retry_batch(
    batch_id: int,
    dimensions: list[str] | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("legal", "finance", "admin")),
) -> BatchRetryOut:
    batch = db.query(AuditBatch).filter(AuditBatch.id == batch_id).with_for_update().first()
    if not batch:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "审查批次不存在")
    _require_batch_access(batch, user)

    if dimensions is None:
        try:
            effective_dimensions = json.loads(batch.dimensions_json or "[]")
        except (TypeError, ValueError):
            effective_dimensions = []
    else:
        effective_dimensions = dimensions
        batch.dimensions_json = json.dumps(dimensions, ensure_ascii=False)

    pending_dispatch: list[AuditBatchItem] = []
    for item in batch.items:
        if item.status != "failed":
            continue
        decision = retry_failed_item(item.status, attempts=item.attempts)
        item.status = decision.status
        item.attempts = decision.attempts
        item.error = None
        item.error_code = None
        item.finished_at = None
        item.task_id = None
        pending_dispatch.append(item)

    _refresh_batch(batch)
    db.commit()

    retried = 0
    for item in pending_dispatch:
        try:
            item.task_id = _dispatch_item(item, effective_dimensions)
            retried += 1
        except Exception as exc:
            _mark_dispatch_pending(item, exc)
    _refresh_batch(batch)
    db.commit()
    return BatchRetryOut(batch_id=batch.id, retried=retried, status=batch.status)
