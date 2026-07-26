"""持久化异步审查批次：创建、查询与失败项重试。"""
import json
import os
import uuid
from dataclasses import dataclass

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.core.config import settings
from app.core.crypto import encrypt_bytes
from app.db.session import get_db
from app.models.models import AuditBatch, AuditBatchItem, AuditLog, Contract, User
from app.schemas.batch import BatchOut, BatchRetryOut
from app.services.batch.service import retry_failed_item, summarize

router = APIRouter()

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
    from app.tasks.audit_tasks import run_contract_audit

    task = run_contract_audit.delay(item.contract_id, dimensions, item.id)
    return str(task.id)


def _refresh_batch(batch: AuditBatch) -> None:
    progress = summarize([item.status for item in batch.items])
    batch.status = progress.status
    batch.total = progress.total
    batch.completed = progress.completed
    batch.failed = progress.failed


def _require_batch_access(batch: AuditBatch, user: User) -> None:
    if user.role != "admin" and batch.department != user.department:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "无权访问其他部门的审查批次")


@router.post("", response_model=BatchOut, status_code=status.HTTP_202_ACCEPTED)
def create_batch(
    files: list[UploadFile] = File(...),
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    contract_type: str = Form(""),
    dimensions: list[str] = Form(default=[]),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("legal", "finance", "admin")),
) -> BatchOut:
    """原子创建加密批次；解析和审查全部提交给 Celery worker。"""
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
    os.makedirs(settings.storage_path, exist_ok=True)
    created_paths: list[str] = []
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
                contract_type=contract_type,
                department=user.department,
                status="uploaded",
                uploaded_by=user.id,
            )
            db.add(contract)
            db.flush()
            batch.items.append(AuditBatchItem(
                contract_id=contract.id,
                filename=upload.filename,
                status="queued",
            ))

        db.add(AuditLog(
            user_id=user.id,
            action="batch_create",
            target=f"batch:{batch.id}",
            detail=f"files={len(uploads)},dimensions={','.join(dimensions) or 'all'}",
        ))
        db.commit()
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
        _cleanup_created_files(created_paths)
        raise HTTPException(status.HTTP_409_CONFLICT, "批次幂等键冲突")
    except HTTPException:
        db.rollback()
        _cleanup_created_files(created_paths)
        raise
    except Exception as exc:
        db.rollback()
        _cleanup_created_files(created_paths)
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "批次创建失败，已回滚") from exc

    for item in batch.items:
        try:
            item.task_id = _dispatch_item(item, dimensions)
        except Exception as exc:
            item.status = "failed"
            item.error = f"任务派发失败: {str(exc)[:240]}"
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
            item.status = "failed"
            item.error = f"任务派发失败: {str(exc)[:240]}"
    _refresh_batch(batch)
    db.commit()
    return BatchRetryOut(batch_id=batch.id, retried=retried, status=batch.status)
