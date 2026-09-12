"""可恢复合同导入收件箱端点。"""

import hashlib
import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Response, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_department_access
from app.core.config import settings
from app.core.crypto import encrypt_bytes
from app.db.session import get_db
from app.models.models import (
    AuditLog,
    Contract,
    ImportAppendRequest,
    ImportBatch,
    ImportBatchItem,
    User,
)
from app.schemas.import_batch import ConfirmImportItem, ImportBatchOut, ImportItemOut
from app.services.imports.service import summarize_import
from app.tasks.dispatcher import dispatch_import_item

router = APIRouter()

_ALLOWED_EXTENSIONS = frozenset({".pdf", ".docx", ".txt"})
_MAX_BATCH_FILES = 200
_MAX_TOTAL_BYTES = 500 * 1024 * 1024


@dataclass(frozen=True)
class PreparedUpload:
    filename: str
    extension: str
    content: bytes
    content_sha256: str


def _prepare_uploads(files: list[UploadFile]) -> list[PreparedUpload]:
    prepared: list[PreparedUpload] = []
    for file in files:
        filename = os.path.basename(file.filename or "unknown")
        content = file.file.read()
        prepared.append(PreparedUpload(
            filename=filename,
            extension=os.path.splitext(filename)[1].lower(),
            content=content,
            content_sha256=hashlib.sha256(content).hexdigest(),
        ))
    return prepared


def _request_fingerprint(department: str, uploads: list[PreparedUpload]) -> str:
    payload = {
        "department": department,
        "files": [
            {
                "filename": upload.filename,
                "size": len(upload.content),
                "content_sha256": upload.content_sha256,
            }
            for upload in uploads
        ],
    }
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _raise_idempotency_conflict() -> None:
    raise HTTPException(
        status.HTTP_409_CONFLICT,
        {"code": "IDEMPOTENCY_CONFLICT", "message": "幂等键已用于其他合同上传请求"},
    )


def _append_prepared_uploads(
    batch: ImportBatch,
    uploads: list[PreparedUpload],
    *,
    department: str,
    operation_key: str,
    created_paths: list[str],
) -> list[ImportBatchItem]:
    new_items: list[ImportBatchItem] = []
    total_bytes = 0
    filenames = {
        item.filename
        for item in batch.items
        if item.status != "deleted"
    }
    for index, upload in enumerate(uploads):
        total_bytes += len(upload.content)
        error_code = None
        error_message = None
        if upload.filename in filenames:
            error_code, error_message = "DUPLICATE_FILENAME", "本批次存在同名文件"
        elif upload.extension not in _ALLOWED_EXTENSIONS:
            error_code, error_message = "UNSUPPORTED_FILE_TYPE", "不支持的文件类型"
        elif not upload.content:
            error_code, error_message = "EMPTY_FILE", "文件为空"
        elif len(upload.content) > settings.MAX_UPLOAD_MB * 1024 * 1024:
            error_code, error_message = "FILE_TOO_LARGE", "文件超过大小限制"
        elif total_bytes > _MAX_TOTAL_BYTES:
            error_code, error_message = "BATCH_TOO_LARGE", "批次总大小超过 500MB"
        filenames.add(upload.filename)

        if error_code:
            item = ImportBatchItem(
                filename=upload.filename,
                status="failed",
                error_code=error_code,
                error_message=error_message,
            )
        else:
            stored_path = os.path.join(
                settings.storage_path,
                f"{uuid.uuid4().hex}{upload.extension}",
            )
            with open(stored_path, "wb") as stream:
                stream.write(encrypt_bytes(upload.content))
            created_paths.append(stored_path)
            contract = Contract(
                filename=upload.filename,
                storage_path=stored_path,
                contract_type="",
                department=department,
                status="uploaded",
                uploaded_by=batch.owner_id,
                upload_idempotency_key=hashlib.sha256(
                    f"{operation_key}:{index}".encode()
                ).hexdigest(),
                content_sha256=upload.content_sha256,
            )
            item = ImportBatchItem(filename=upload.filename, contract=contract, status="queued")
        batch.items.append(item)
        new_items.append(item)
    return new_items


def _dispatch_import_item(item_id: int) -> str:
    return dispatch_import_item(item_id)


def _item_out(item: ImportBatchItem) -> ImportItemOut:
    contract = item.contract
    return ImportItemOut(
        id=item.id,
        contract_id=item.contract_id,
        filename=item.filename,
        status=item.status,
        error_code=item.error_code,
        error_message=item.error_message,
        suggested_type=contract.suggested_type if contract else "",
        confidence=contract.type_confidence if contract else None,
        confirmed_type=contract.contract_type if contract else "",
        department=contract.department if contract else "",
        requires_review=contract.requires_review if contract else False,
    )


def _refresh_batch(batch: ImportBatch) -> None:
    summary = summarize_import([item.status for item in batch.items])
    batch.total = summary.total
    batch.ready = summary.ready
    batch.failed = summary.failed
    batch.status = summary.status


def _batch_out(batch: ImportBatch) -> ImportBatchOut:
    _refresh_batch(batch)
    return ImportBatchOut(
        id=batch.id,
        status=batch.status,
        total=batch.total,
        ready=batch.ready,
        failed=batch.failed,
        created_at=batch.created_at,
        updated_at=batch.updated_at,
        items=[_item_out(item) for item in batch.items if item.status != "deleted"],
    )


def _get_batch(db: Session, batch_id: int, user: User) -> ImportBatch:
    batch = db.query(ImportBatch).filter(ImportBatch.id == batch_id).first()
    if not batch:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "导入批次不存在")
    if user.role == "admin" or batch.owner_id == user.id:
        return batch
    departments = {
        item.contract.department
        for item in batch.items
        if item.contract is not None and item.status != "deleted"
    }
    if not departments:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "无权访问该导入批次")
    for department in departments:
        require_department_access(user, department)
    return batch


def _get_item(db: Session, batch_id: int, item_id: int, user: User) -> tuple[ImportBatch, ImportBatchItem]:
    batch = _get_batch(db, batch_id, user)
    item = next((candidate for candidate in batch.items if candidate.id == item_id), None)
    if not item:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "导入项不存在")
    if item.contract:
        require_department_access(user, item.contract.department)
    return batch, item


@router.post("", response_model=ImportBatchOut, status_code=status.HTTP_202_ACCEPTED)
def create_import(
    files: list[UploadFile] = File(...),
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    department: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ImportBatchOut:
    key = idempotency_key.strip()
    if not 8 <= len(key) <= 128:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Idempotency-Key 长度必须为 8 至 128")
    if not files or len(files) > _MAX_BATCH_FILES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "单次必须上传 1 至 200 份合同")
    target_department = (department or user.department).strip()
    require_department_access(user, target_department)
    uploads = _prepare_uploads(files)
    request_fingerprint = _request_fingerprint(target_department, uploads)
    existing = db.query(ImportBatch).filter(
        ImportBatch.owner_id == user.id,
        ImportBatch.idempotency_key == key,
    ).first()
    if existing:
        if existing.request_fingerprint and existing.request_fingerprint != request_fingerprint:
            _raise_idempotency_conflict()
        return _batch_out(existing)

    batch = ImportBatch(
        owner_id=user.id,
        idempotency_key=key,
        request_fingerprint=request_fingerprint,
        total=len(uploads),
    )
    db.add(batch)
    db.flush()
    os.makedirs(settings.storage_path, exist_ok=True)
    created_paths: list[str] = []
    try:
        new_items = _append_prepared_uploads(
            batch,
            uploads,
            department=target_department,
            operation_key=key,
            created_paths=created_paths,
        )
        db.add(AuditLog(
            user_id=user.id,
            action="import_create",
            target=f"import:{batch.id}",
            detail=f"files={len(files)},department={target_department}",
        ))
        _refresh_batch(batch)
        db.commit()
        db.refresh(batch)
    except Exception:
        db.rollback()
        for path in created_paths:
            if os.path.isfile(path):
                os.unlink(path)
        raise

    for item in new_items:
        if item.status != "queued":
            continue
        try:
            _dispatch_import_item(item.id)
        except Exception:
            item.error_code = "DISPATCH_PENDING"
            item.error_message = "文件已保存，正在等待重新解析"
    db.commit()
    return _batch_out(batch)


@router.post("/{batch_id}/items", response_model=ImportBatchOut, status_code=status.HTTP_202_ACCEPTED)
def append_import_items(
    batch_id: int,
    files: list[UploadFile] = File(...),
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ImportBatchOut:
    key = idempotency_key.strip()
    if not 8 <= len(key) <= 128:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Idempotency-Key 长度必须为 8 至 128")
    if not files or len(files) > _MAX_BATCH_FILES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "单次必须上传 1 至 200 份合同")

    batch = _get_batch(db, batch_id, user)
    if user.role != "admin" and batch.owner_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "只有收件箱所有者可以继续添加合同")
    departments = {
        item.contract.department
        for item in batch.items
        if item.contract is not None and item.status != "deleted"
    }
    target_department = next(iter(departments), user.department).strip()
    require_department_access(user, target_department)
    uploads = _prepare_uploads(files)
    request_fingerprint = _request_fingerprint(target_department, uploads)
    existing_request = db.query(ImportAppendRequest).filter(
        ImportAppendRequest.batch_id == batch.id,
        ImportAppendRequest.idempotency_key == key,
    ).first()
    if existing_request:
        if existing_request.request_fingerprint != request_fingerprint:
            _raise_idempotency_conflict()
        return _batch_out(batch)
    visible_count = sum(item.status != "deleted" for item in batch.items)
    if visible_count + len(uploads) > _MAX_BATCH_FILES:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {
                "code": "IMPORT_BATCH_LIMIT_EXCEEDED",
                "message": "单个收件箱最多包含 200 份合同",
            },
        )

    os.makedirs(settings.storage_path, exist_ok=True)
    created_paths: list[str] = []
    try:
        db.add(ImportAppendRequest(
            batch_id=batch.id,
            idempotency_key=key,
            request_fingerprint=request_fingerprint,
        ))
        new_items = _append_prepared_uploads(
            batch,
            uploads,
            department=target_department,
            operation_key=key,
            created_paths=created_paths,
        )

        db.add(AuditLog(
            user_id=user.id,
            action="import_append",
            target=f"import:{batch.id}",
            detail=f"files={len(uploads)},department={target_department}",
        ))
        _refresh_batch(batch)
        db.commit()
        db.refresh(batch)
    except Exception:
        db.rollback()
        for path in created_paths:
            if os.path.isfile(path):
                os.unlink(path)
        raise

    for item in new_items:
        if item.status != "queued":
            continue
        try:
            _dispatch_import_item(item.id)
        except Exception:
            item.error_code = "DISPATCH_PENDING"
            item.error_message = "文件已保存，正在等待重新解析"
    db.commit()
    return _batch_out(batch)


@router.get("/{batch_id}", response_model=ImportBatchOut)
def get_import(
    batch_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ImportBatchOut:
    batch = _get_batch(db, batch_id, user)
    return _batch_out(batch)


@router.patch("/{batch_id}/items/{item_id}", response_model=ImportItemOut)
def confirm_item(
    batch_id: int,
    item_id: int,
    body: ConfirmImportItem,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ImportItemOut:
    batch, item = _get_item(db, batch_id, item_id, user)
    if not item.contract or item.status not in {"awaiting_confirmation", "ready"}:
        raise HTTPException(status.HTTP_409_CONFLICT, "当前导入项不能确认")
    require_department_access(user, body.department)
    before = {"type": item.contract.contract_type, "department": item.contract.department}
    item.contract.contract_type = body.contract_type.strip()
    item.contract.department = body.department.strip()
    item.contract.type_confirmed_by = user.id
    item.contract.type_confirmed_at = datetime.now(timezone.utc)
    item.status = "ready"
    db.add(AuditLog(
        user_id=user.id,
        action="contract_type_confirm",
        target=f"contract:{item.contract.id}",
        detail=f"before={before},type={item.contract.contract_type},department={item.contract.department}",
    ))
    _refresh_batch(batch)
    db.commit()
    db.refresh(item)
    return _item_out(item)


@router.post("/{batch_id}/items/{item_id}/retry", response_model=ImportItemOut)
def retry_item(
    batch_id: int,
    item_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ImportItemOut:
    batch, item = _get_item(db, batch_id, item_id, user)
    if item.status != "failed" or item.contract is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "仅解析失败的合同可以重试")
    item.status = "queued"
    item.error_code = None
    item.error_message = None
    _refresh_batch(batch)
    db.commit()
    _dispatch_import_item(item.id)
    db.refresh(item)
    return _item_out(item)


@router.delete("/{batch_id}/items/{item_id}/record", status_code=status.HTTP_204_NO_CONTENT)
def remove_failed_record(
    batch_id: int,
    item_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    batch, item = _get_item(db, batch_id, item_id, user)
    if item.status != "failed" or item.contract_id is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "该记录已生成合同，不能直接移出")
    db.delete(item)
    db.flush()
    _refresh_batch(batch)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/{batch_id}/items/{item_id}/draft", response_model=ImportItemOut)
def delete_contract_draft(
    batch_id: int,
    item_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ImportItemOut:
    batch, item = _get_item(db, batch_id, item_id, user)
    contract = item.contract
    if not contract or item.status in {"auditing", "done"} or contract.status in {"auditing", "done"}:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {"code": "CONTRACT_BUSY", "message": "审查中或已审查合同不能删除"},
        )
    contract.deleted_at = datetime.now(timezone.utc)
    contract.deleted_by = user.id
    item.status = "deleted"
    db.add(AuditLog(
        user_id=user.id,
        action="contract_draft_delete",
        target=f"contract:{contract.id}",
        detail=f"retention_days={settings.CONTRACT_TRASH_RETENTION_DAYS}",
    ))
    _refresh_batch(batch)
    db.commit()
    db.refresh(item)
    return _item_out(item)


@router.post("/{batch_id}/items/{item_id}/restore", response_model=ImportItemOut)
def restore_contract_draft(
    batch_id: int,
    item_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ImportItemOut:
    if user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "仅管理员可以恢复合同草稿")
    batch, item = _get_item(db, batch_id, item_id, user)
    contract = item.contract
    if not contract or item.status != "deleted" or contract.deleted_at is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "合同草稿不在回收站")
    deleted_at = contract.deleted_at
    if deleted_at.tzinfo is None:
        deleted_at = deleted_at.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) - deleted_at > timedelta(days=settings.CONTRACT_TRASH_RETENTION_DAYS):
        raise HTTPException(status.HTTP_410_GONE, "合同草稿已超过恢复期限")
    contract.deleted_at = None
    contract.deleted_by = None
    item.status = "awaiting_confirmation" if not contract.contract_type else "ready"
    db.add(AuditLog(user_id=user.id, action="contract_draft_restore", target=f"contract:{contract.id}"))
    _refresh_batch(batch)
    db.commit()
    db.refresh(item)
    return _item_out(item)
