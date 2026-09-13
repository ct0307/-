"""合同端点：上传、解析、触发审查、查询。"""
import hashlib
import json
import os
import uuid
from datetime import timezone

from fastapi import APIRouter, Depends, File, Header, HTTPException, UploadFile, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import allowed_departments, get_current_user, require_roles
from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import get_db
from app.models.models import AuditBatchItem, Contract, Risk, User
from app.schemas.contract import (
    AuditRequest,
    AuditResponse,
    ContractOut,
    CrossCheckOut,
    HistoryRow,
    ParseErrorResponse,
    ParseResponse,
    RiskOut,
)
from app.services import audit_log
from app.services import masking
from app.services.audit.jobs import AuditJobConflict, create_single_audit_job
from app.services.audit.result_snapshot import quality_snapshot, safe_coverage
from app.services.audit.runner import apply_parse_quality, run_audit
from app.services.parser.extractor import (
    extract_document,
    extract_elements,
)
from app.services.parser.ocr import OCRError, OCRUnavailable
from app.tasks.dispatcher import dispatch_audit_item

router = APIRouter()
log = get_logger("contracts")

_ALLOWED_EXT = {".pdf", ".docx", ".txt"}

# 风险等级聚合：取最高等级
_LEVEL_RANK = {"high": 2, "medium": 1, "low": 0}
_LEVEL_ZH = {2: "高风险", 1: "中风险", 0: "低风险"}

_PARSE_ERROR_DETAILS = {
    "PDF_TEXT_ENCODING_ERROR": (
        status.HTTP_422_UNPROCESSABLE_ENTITY,
        "PDF 文本编码异常，请重新导出 PDF 后重试",
    ),
    "PDF_TEXT_EMPTY": (
        status.HTTP_422_UNPROCESSABLE_ENTITY,
        "未能从文件中提取有效文本，请上传含文本层的文件",
    ),
    "OCR_UNAVAILABLE": (
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "OCR 服务暂不可用，请稍后重试或上传含文本层的文件",
    ),
    "OCR_PROCESSING_ERROR": (
        status.HTTP_422_UNPROCESSABLE_ENTITY,
        "OCR 未能识别文件内容，请检查文件清晰度后重试",
    ),
    "PARSE_INTERNAL_ERROR": (
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        "合同解析失败，请稍后重试",
    ),
}


def _parse_error_code(exc: Exception) -> str:
    if isinstance(exc, UnicodeError):
        return "PDF_TEXT_ENCODING_ERROR"
    if isinstance(exc, OCRUnavailable):
        return "OCR_UNAVAILABLE"
    if isinstance(exc, OCRError):
        return "OCR_PROCESSING_ERROR"
    return "PARSE_INTERNAL_ERROR"


def _raise_parse_error(contract_id: int, exc: Exception, *, code: str | None = None) -> None:
    error_code = code or _parse_error_code(exc)
    status_code, detail = _PARSE_ERROR_DETAILS[error_code]
    log.error(
        "contract.parse_failed",
        contract_id=contract_id,
        code=error_code,
        exception_type=type(exc).__name__,
    )
    raise HTTPException(
        status_code=status_code,
        detail={"code": error_code, "detail": detail},
    ) from exc


def _dept_accessible(contract, user) -> bool:
    """管理员可访问全量，其他角色仅访问当前授权部门。"""
    return user.role == "admin" or contract.department in allowed_departments(user)


# 审查状态推导：人工复核优先；其次是整改状态；其余为合规。
def _derive_status(contract: Contract, risks: list) -> str:
    if contract.status == "review_required" or contract.requires_review:
        return "待人工复核"
    if not risks:
        return "合规"
    if any(r.review_status in ("pending", "to_modify") for r in risks):
        return "待整改"
    if contract.status == "done":
        return "已整改"
    return "合规"


def _derive_level(risks: list) -> str:
    if not risks:
        return "低风险"
    max_rank = max(_LEVEL_RANK.get(r.level, 0) for r in risks)
    return _LEVEL_ZH[max_rank]


@router.get("", response_model=list[HistoryRow])
def list_contracts_history(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[HistoryRow]:
    """审查历史台账：返回全部合同（最新在前），含聚合风险等级与处理状态。

    搜索/筛选/分页全在前端本地处理，端点直接返回裸数组。
    """
    contracts = db.query(Contract).filter(Contract.deleted_at.is_(None)).order_by(Contract.id.desc()).all()
    # 部门访问隔离：business 角色只看本部门合同
    contracts = [c for c in contracts if _dept_accessible(c, user)]
    # 批量预取上传者（避免 N+1）
    user_ids = {c.uploaded_by for c in contracts}
    users = {u.id: u for u in db.query(User).filter(User.id.in_(user_ids)).all()}
    result: list[HistoryRow] = []
    for c in contracts:
        risks = db.query(Risk).filter(Risk.contract_id == c.id).all()
        submitter_obj = users.get(c.uploaded_by)
        # 时间格式 YYYY-MM-DD HH:mm（本地化显示，非 ISO）
        dt = c.created_at
        if dt.tzinfo is not None:
            # SQLite 以 UTC 存储，直接取 naive 字符串
            dt = dt.replace(tzinfo=None)
        time_str = dt.strftime("%Y-%m-%d %H:%M") if dt else ""
        submitter_raw = submitter_obj.username if submitter_obj else ""
        result.append(HistoryRow(
            id=f"C{c.id:04d}",
            name=c.filename,
            type=c.contract_type or "",
            submitter=masking.apply_history_row_masking({"submitter": submitter_raw}, user.role)["submitter"],
            time=time_str,
            level=_derive_level(risks),
            riskCount=len(risks),
            status=_derive_status(c, risks),
        ))
    return result


@router.post("/batch-upload")
def batch_upload_contracts(
    files: list[UploadFile] = File(..., description="批量上传合同文件，最多50份"),
    contract_type: str = "",
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(["legal", "finance", "admin"])),
) -> list[dict]:
    """批量上传合同：一次最多50份，逐文件处理。

    每份文件独立上传 + 加密存储 + 文本解析，互不影响（单文件失败不中断其余）。
    返回每份文件的处理结果列表，包含 contract_id / status / error。
    """
    if len(files) > 200:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "单次最多上传 200 份合同")
    confirmed_type = contract_type.strip()
    if not confirmed_type:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "请先确认合同类型")

    from app.core.crypto import encrypt_bytes, is_encryption_enabled
    encrypted_flag = is_encryption_enabled()
    os.makedirs(settings.storage_path, exist_ok=True)
    results = []

    for file in files:
        fname = file.filename or "unknown"
        ext = os.path.splitext(fname)[1].lower()
        stored_path: str | None = None
        contract_id: int | None = None
        committed = False
        try:
            if ext not in _ALLOWED_EXT:
                results.append({"filename": fname, "status": "failed", "error": f"不支持的文件类型 {ext}"})
                continue
            content = file.file.read()
            if len(content) > settings.MAX_UPLOAD_MB * 1024 * 1024:
                results.append({"filename": fname, "status": "failed", "error": "文件超过大小限制"})
                continue

            stored_name = f"{uuid.uuid4().hex}{ext}"
            stored_path = os.path.join(settings.storage_path, stored_name)
            with open(stored_path, "wb") as f:
                f.write(encrypt_bytes(content))

            contract = Contract(
                filename=fname,
                storage_path=stored_path,
                contract_type=confirmed_type,
                department=user.department,
                status="uploaded",
                uploaded_by=user.id,
            )
            db.add(contract)
            db.flush()  # 获取 id 但不提交，出错可回滚
            contract_id = contract.id

            # 解析并写入 elements_json
            try:
                parsed = extract_document(stored_path)
                apply_parse_quality(contract, parsed)
                elements = extract_elements(parsed.text)
                contract.elements_json = json.dumps(
                    {k: v for k, v in elements.items() if isinstance(v, (str, type(None)))},
                    ensure_ascii=False,
                )
                contract.status = "parsed"
            except Exception:
                pass  # 解析失败不影响上传结果

            audit_log.record(db, user_id=user.id, action="batch_upload",
                             target=f"contract:{contract.id}", detail=f"{fname} encrypted={encrypted_flag}")
            db.commit()
            committed = True
            db.refresh(contract)
            results.append({"filename": fname, "status": "success", "contract_id": contract.id})
        except Exception as exc:
            db.rollback()
            if committed and contract_id is not None:
                log.warning(
                    "contract.batch_upload_response_unconfirmed",
                    filename=fname,
                    contract_id=contract_id,
                    exception_type=type(exc).__name__,
                )
                results.append({
                    "filename": fname,
                    "status": "success",
                    "contract_id": contract_id,
                    "warning": "合同已上传，但响应确认失败",
                })
                continue
            if not committed and stored_path and os.path.isfile(stored_path):
                os.unlink(stored_path)
            log.error(
                "contract.batch_upload_failed",
                filename=fname,
                exception_type=type(exc).__name__,
            )
            results.append({"filename": fname, "status": "failed", "error": "合同上传失败，已回滚"})

    return results


@router.post("/upload", response_model=ContractOut)
def upload_contract(
    file: UploadFile,
    contract_type: str = "",
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Contract:
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in _ALLOWED_EXT:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"不支持的文件类型: {ext}")

    os.makedirs(settings.storage_path, exist_ok=True)
    stored_name = f"{uuid.uuid4().hex}{ext}"
    stored_path = os.path.join(settings.storage_path, stored_name)
    content = file.file.read()
    if len(content) > settings.MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "文件超过大小限制")

    content_sha256 = hashlib.sha256(content).hexdigest()
    key = (idempotency_key or f"sha256:{content_sha256}").strip()
    if not 8 <= len(key) <= 128:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Idempotency-Key 长度必须为 8 至 128")
    existing = db.query(Contract).filter(
        Contract.uploaded_by == user.id,
        Contract.upload_idempotency_key == key,
    ).first()
    if existing:
        if existing.deleted_at is not None:
            existing.upload_idempotency_key = None
            db.flush()
        elif existing.content_sha256 != content_sha256:
            raise HTTPException(status.HTTP_409_CONFLICT, "上传幂等键与文件内容不一致")
        else:
            return existing

    # 加密存储：启用 FILE_ENCRYPT_KEY 时落盘前加密，防止明文泄漏
    from app.core.crypto import encrypt_bytes, is_encryption_enabled
    to_write = encrypt_bytes(content)
    encrypted = is_encryption_enabled()
    created_path = False
    committed = False
    try:
        with open(stored_path, "wb") as f:
            f.write(to_write)
        created_path = True

        contract = Contract(
            filename=file.filename or stored_name,
            storage_path=stored_path,
            contract_type=contract_type,
            department=user.department,
            status="uploaded",
            uploaded_by=user.id,
            upload_idempotency_key=key,
            content_sha256=content_sha256,
        )
        db.add(contract)
        db.flush()
        audit_log.record(
            db, user_id=user.id, action="upload",
            target=f"contract:{contract.id}",
            detail=f"{contract.filename} encrypted={encrypted}",
        )
        db.commit()
        committed = True
        db.refresh(contract)
        return contract
    except IntegrityError as exc:
        db.rollback()
        if not committed and created_path and os.path.isfile(stored_path):
            os.unlink(stored_path)
        duplicate = db.query(Contract).filter(
            Contract.uploaded_by == user.id,
            Contract.upload_idempotency_key == key,
        ).first()
        if duplicate and duplicate.content_sha256 == content_sha256:
            return duplicate
        raise HTTPException(status.HTTP_409_CONFLICT, "上传幂等键冲突") from exc
    except HTTPException:
        db.rollback()
        if not committed and created_path and os.path.isfile(stored_path):
            os.unlink(stored_path)
        raise
    except Exception as exc:
        db.rollback()
        if not committed and created_path and os.path.isfile(stored_path):
            os.unlink(stored_path)
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "合同上传失败，已回滚") from exc


@router.post(
    "/{contract_id}/parse",
    response_model=ParseResponse,
    responses={
        422: {"model": ParseErrorResponse},
        503: {"model": ParseErrorResponse},
        500: {"model": ParseErrorResponse},
    },
)
def parse_contract(
    contract_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ParseResponse:
    contract = _get_contract(db, contract_id, user)
    try:
        parsed = extract_document(contract.storage_path)
        if not parsed.text.strip():
            empty_error = ValueError("empty document text")
            db.rollback()
            _raise_parse_error(contract_id, empty_error, code="PDF_TEXT_EMPTY")
        apply_parse_quality(contract, parsed)
        # 同步解析只做确定性抽取；耗时且不确定的模型调用统一进入可恢复审查任务。
        elements = extract_elements(parsed.text)
        contract.status = "parsed"
        contract.elements_json = json.dumps(
            {k: v for k, v in elements.items() if isinstance(v, (str, type(None)))},
            ensure_ascii=False,
        )
        audit_log.record(db, user_id=user.id, action="parse", target=f"contract:{contract_id}")
        db.commit()
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        _raise_parse_error(contract_id, exc)
    return ParseResponse(
        contract_id=contract_id,
        elements=elements,
        text_length=len(parsed.text),
        requires_review=contract.requires_review,
        ocr_confidence=contract.ocr_confidence,
        review_reason=contract.review_reason,
    )


@router.post("/{contract_id}/audit", response_model=AuditResponse)
def audit_contract_endpoint(
    contract_id: int,
    body: AuditRequest = AuditRequest(),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("legal", "finance")),
) -> AuditResponse:
    contract = _get_contract(db, contract_id, user)
    confirmed_type = body.contract_type.strip()
    if not confirmed_type:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "请先确认合同类型")
    dimensions = body.dimensions or []
    key = (idempotency_key or f"audit:{uuid.uuid4().hex}").strip()
    try:
        creation = create_single_audit_job(
            db,
            contract=contract,
            user=user,
            idempotency_key=key,
            contract_type=confirmed_type,
            dimensions=dimensions,
        )
    except AuditJobConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    item = creation.item
    if creation.created:
        try:
            item.task_id = dispatch_audit_item(
                item,
                json.loads(creation.batch.dimensions_json or "[]"),
            )
            item.error_code = None
            item.error = None
        except Exception as exc:  # noqa: BLE001
            item.error_code = "DISPATCH_PENDING"
            item.error = "任务已保存，正在等待重新派发"
            log.error(
                "audit.dispatch_pending",
                contract_id=contract_id,
                job_id=item.id,
                exception_type=type(exc).__name__,
            )
        db.commit()
        db.refresh(item)

    return _audit_response_from_item(contract, item)


@router.get("/{contract_id}/audit-status", response_model=AuditResponse)
def get_contract_audit_status(
    contract_id: int,
    job_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AuditResponse:
    contract = _get_contract(db, contract_id, user)
    item_query = db.query(AuditBatchItem).filter(
        AuditBatchItem.contract_id == contract_id
    )
    if job_id is not None:
        item = item_query.filter(AuditBatchItem.id == job_id).first()
        if not item:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "审查任务不存在")
    else:
        item = item_query.order_by(AuditBatchItem.id.desc()).first()
    if item is not None:
        return _audit_response_from_item(contract, item)
    risk_count = db.query(Risk).filter(Risk.contract_id == contract_id).count()
    return _audit_response_from_item(
        contract,
        None,
        fallback_risk_count=risk_count,
    )


def _audit_response_from_item(
    contract: Contract,
    item: AuditBatchItem | None,
    *,
    fallback_risk_count: int | None = None,
) -> AuditResponse:
    """从选定任务快照构造响应；任务存在时不读取合同当前代次质量。"""
    quality = quality_snapshot(item, contract) if item is not None else None
    result = quality.result if quality is not None else {}
    raw_status = item.status if item is not None else contract.status
    response_status = {
        "failed": "audit_failed",
        "auditing": "reviewing",
    }.get(raw_status, raw_status)
    if response_status not in {
        "queued", "parsing", "reviewing", "validating",
        "done", "review_required", "audit_failed",
    }:
        response_status = "audit_failed"

    risk_count = result.get("risk_count")
    if (
        not isinstance(risk_count, int)
        or isinstance(risk_count, bool)
        or risk_count < 0
    ):
        risk_count = fallback_risk_count if item is None else None

    raw_cross_checks = result.get("cross_checks", [])
    cross_checks: list[CrossCheckOut] = []
    if isinstance(raw_cross_checks, list):
        for value in raw_cross_checks:
            if not isinstance(value, dict):
                continue
            try:
                cross_checks.append(_to_cross_out(value))
            except (KeyError, TypeError, ValueError):
                continue

    requires_review = (
        quality.requires_review
        if quality is not None
        else response_status == "review_required" or bool(contract.requires_review)
    )
    ocr_confidence = quality.ocr_confidence if quality is not None else contract.ocr_confidence
    review_reason = quality.review_reason if quality is not None else (
        contract.review_reason if requires_review else None
    )

    quality_reasons = result.get("quality_reasons", [])
    if not isinstance(quality_reasons, list) or not all(
        isinstance(value, str) for value in quality_reasons
    ):
        quality_reasons = []
    issues = result.get("issues", [])
    if not isinstance(issues, list):
        issues = []
    issues = [value for value in issues if isinstance(value, dict)]
    coverage = safe_coverage(result.get("coverage"))
    retryable_codes = {
        "DISPATCH_PENDING",
        "MODEL_TIMEOUT",
        "MODEL_UNAVAILABLE",
        "NETWORK_UNCERTAIN",
    }
    return AuditResponse(
        contract_id=contract.id,
        status=response_status,
        risk_count=risk_count,
        cross_checks=cross_checks,
        task_id=item.task_id if item is not None else None,
        batch_id=item.batch_id if item is not None else None,
        job_id=item.id if item is not None else None,
        error_code=item.error_code if item is not None else None,
        error_message=item.error if item is not None else None,
        retryable=bool(item is not None and item.error_code in retryable_codes),
        requires_review=requires_review,
        ocr_confidence=ocr_confidence,
        review_reason=review_reason,
        quality_reasons=quality_reasons,
        issues=issues,
        coverage=coverage,
    )


def _to_cross_out(c: dict) -> CrossCheckOut:
    """把 auditor 的冲突项 dict（键含保留字 from/to）映射到 schema。"""
    return CrossCheckOut(
        id=c["id"],
        from_agent=c.get("from_agent", c.get("from", "")),
        to_agent=c.get("to_agent", c.get("to", "")),
        trigger=c["trigger"],
        action=c["action"],
        verdict=c["verdict"],
        note=c["note"],
        category=c["category"],
    )


@router.get("/{contract_id}/risks")
def get_contract_risks(
    contract_id: int,
    job_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list:
    """风险列表：business 角色的原文字段截断脱敏，其他角色完整返回。"""
    _get_contract(db, contract_id, user)
    risk_query = db.query(Risk).filter(Risk.contract_id == contract_id)
    if job_id is not None:
        item = db.query(AuditBatchItem).filter(
            AuditBatchItem.id == job_id,
            AuditBatchItem.contract_id == contract_id,
        ).first()
        if not item:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "审查任务不存在")
        if item.audit_generation > 0:
            risk_query = risk_query.filter(Risk.audit_job_id == job_id)
        else:
            risk_query = risk_query.filter(Risk.audit_job_id.is_(None))
    risks = risk_query.all()
    if masking.is_full_access(user.role):
        # 高权限角色：走 Pydantic 序列化，类型安全
        return [RiskOut.model_validate(r) for r in risks]
    # business 角色：原文截断脱敏后返回
    return [masking.apply_risk_masking(r, user.role) for r in risks]


def _get_contract(db: Session, contract_id: int, user: User | None = None) -> Contract:
    contract = db.query(Contract).filter(
        Contract.id == contract_id,
        Contract.deleted_at.is_(None),
    ).first()
    if not contract:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "合同不存在")
    if user and not _dept_accessible(contract, user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "无权访问此合同（部门隔离）")
    return contract


@router.patch("/{contract_id}/escalate", status_code=status.HTTP_200_OK)
def escalate_contract(
    contract_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["legal", "finance", "admin"])),
):
    """三方会审发起：更新合同状态 + 写审计日志。

    语义：当前合同风险等级触发三员会审流程，由法务/财务/管理员发起，
    审批工作流待集成企业 OA（路线图），当前阶段记录发起操作留痕。
    """
    contract = _get_contract(db, contract_id, current_user)
    contract.status = "three_review"
    audit_log.record(
        db,
        user_id=current_user.id,
        action="三方会审发起",
        target=f"合同#{contract_id}",
        detail=f"由 {current_user.username}（{current_user.role}）发起，状态更新为 three_review",
    )
    db.commit()
    return {"contract_id": contract_id, "status": "three_review"}

