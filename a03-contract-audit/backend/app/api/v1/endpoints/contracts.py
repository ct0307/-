"""合同端点：上传、解析、触发审查、查询。"""
import json
import os
import uuid
from datetime import timezone

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.core.config import settings
from app.db.session import get_db
from app.models.models import Contract, Risk, User
from app.schemas.contract import (
    AuditRequest,
    AuditResponse,
    ContractOut,
    CrossCheckOut,
    HistoryRow,
    ParseResponse,
    RiskOut,
)
from app.services import audit_log
from app.services import masking
from app.services.audit.runner import apply_parse_quality, run_audit
from app.services.parser.extractor import (
    extract_document,
    extract_elements,
    extract_elements_with_llm,
)

router = APIRouter()

_ALLOWED_EXT = {".pdf", ".docx", ".txt"}

# 风险等级聚合：取最高等级
_LEVEL_RANK = {"high": 2, "medium": 1, "low": 0}
_LEVEL_ZH = {2: "高风险", 1: "中风险", 0: "低风险"}


def _dept_accessible(contract, user) -> bool:
    """部门访问控制：business 角色只可见本部门合同，其他角色全量可见。"""
    if user.role == "business":
        return contract.department == user.department
    return True


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
    contracts = db.query(Contract).order_by(Contract.id.desc()).all()
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

    from app.core.crypto import encrypt_bytes, is_encryption_enabled
    encrypted_flag = is_encryption_enabled()
    os.makedirs(settings.storage_path, exist_ok=True)
    results = []

    for file in files:
        fname = file.filename or "unknown"
        ext = os.path.splitext(fname)[1].lower()
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
                contract_type=contract_type,
                department=user.department,
                status="uploaded",
                uploaded_by=user.id,
            )
            db.add(contract)
            db.flush()  # 获取 id 但不提交，出错可回滚

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

            db.commit()
            db.refresh(contract)
            audit_log.record(db, user_id=user.id, action="batch_upload",
                             target=f"contract:{contract.id}", detail=f"{fname} encrypted={encrypted_flag}")
            results.append({"filename": fname, "status": "success", "contract_id": contract.id})
        except Exception as exc:
            db.rollback()
            results.append({"filename": fname, "status": "failed", "error": str(exc)})

    return results


@router.post("/upload", response_model=ContractOut)
def upload_contract(
    file: UploadFile,
    contract_type: str = "",
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

    # 加密存储：启用 FILE_ENCRYPT_KEY 时落盘前加密，防止明文泄漏
    from app.core.crypto import encrypt_bytes, is_encryption_enabled
    to_write = encrypt_bytes(content)
    encrypted = is_encryption_enabled()
    with open(stored_path, "wb") as f:
        f.write(to_write)

    contract = Contract(
        filename=file.filename or stored_name,
        storage_path=stored_path,
        contract_type=contract_type,
        department=user.department,
        status="uploaded",
        uploaded_by=user.id,
    )
    db.add(contract)
    db.commit()
    db.refresh(contract)
    audit_log.record(
        db, user_id=user.id, action="upload",
        target=f"contract:{contract.id}",
        detail=f"{contract.filename} encrypted={encrypted}",
    )
    return contract


@router.post("/{contract_id}/parse", response_model=ParseResponse)
def parse_contract(
    contract_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ParseResponse:
    contract = _get_contract(db, contract_id, user)
    parsed = extract_document(contract.storage_path)
    apply_parse_quality(contract, parsed)
    # 精解析：正则 + LLM 语义抽取六要素（供报表/Excel 展示），LLM 失败自动降级正则
    elements = extract_elements_with_llm(parsed.text)
    contract.status = "parsed"
    contract.elements_json = json.dumps(
        {k: v for k, v in elements.items() if isinstance(v, (str, type(None)))},
        ensure_ascii=False,
    )
    db.commit()
    audit_log.record(db, user_id=user.id, action="parse", target=f"contract:{contract_id}")
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
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("legal", "finance")),
) -> AuditResponse:
    contract = _get_contract(db, contract_id, user)
    dimensions = body.dimensions or []

    if settings.AUDIT_ASYNC:
        from app.tasks.audit_tasks import run_contract_audit
        task = run_contract_audit.delay(contract_id, dimensions)
        contract.status = "auditing"
        db.commit()
        audit_log.record(db, user_id=user.id, action="audit_dispatch", target=f"contract:{contract_id}", detail=f"task:{task.id}")
        return AuditResponse(contract_id=contract_id, task_id=task.id, status="auditing")

    result = run_audit(db, contract, dimensions=dimensions)
    dim_detail = f"risks={result['risk_count']},dims={','.join(dimensions) if dimensions else 'all'}"
    audit_log.record(db, user_id=user.id, action="audit", target=f"contract:{contract_id}", detail=dim_detail)
    return AuditResponse(
        contract_id=contract_id,
        status=contract.status,
        risk_count=result["risk_count"],
        cross_checks=[_to_cross_out(c) for c in result["cross_checks"]],
        requires_review=result["requires_review"],
        ocr_confidence=result["ocr_confidence"],
        review_reason=result["review_reason"],
    )


def _to_cross_out(c: dict) -> CrossCheckOut:
    """把 auditor 的冲突项 dict（键含保留字 from/to）映射到 schema。"""
    return CrossCheckOut(
        id=c["id"],
        from_agent=c["from"],
        to_agent=c["to"],
        trigger=c["trigger"],
        action=c["action"],
        verdict=c["verdict"],
        note=c["note"],
        category=c["category"],
    )


@router.get("/{contract_id}/risks")
def get_contract_risks(contract_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list:
    """风险列表：business 角色的原文字段截断脱敏，其他角色完整返回。"""
    _get_contract(db, contract_id, user)
    risks = db.query(Risk).filter(Risk.contract_id == contract_id).all()
    if masking.is_full_access(user.role):
        # 高权限角色：走 Pydantic 序列化，类型安全
        return [RiskOut.model_validate(r) for r in risks]
    # business 角色：原文截断脱敏后返回
    return [masking.apply_risk_masking(r, user.role) for r in risks]


def _get_contract(db: Session, contract_id: int, user: User | None = None) -> Contract:
    contract = db.query(Contract).filter(Contract.id == contract_id).first()
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
    db.commit()
    audit_log.record(
        db,
        current_user.id,
        "三方会审发起",
        f"合同#{contract_id}",
        f"由 {current_user.username}（{current_user.role}）发起，状态更新为 three_review",
    )
    return {"contract_id": contract_id, "status": "three_review"}

