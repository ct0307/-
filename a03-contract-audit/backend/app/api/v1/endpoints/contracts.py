"""合同端点：上传、解析、触发审查、查询。"""
import os
import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.core.config import settings
from app.db.session import get_db
from app.models.models import Contract, Risk, User
from app.schemas.contract import AuditResponse, ContractOut, CrossCheckOut, RiskOut
from app.services import audit_log
from app.services.audit.runner import run_audit
from app.services.parser.extractor import extract_elements, extract_text

router = APIRouter()

_ALLOWED_EXT = {".pdf", ".docx", ".txt"}


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

    # 私有化本地存储：用 uuid 命名避免冲突与路径穿越
    os.makedirs(settings.storage_path, exist_ok=True)
    stored_name = f"{uuid.uuid4().hex}{ext}"
    stored_path = os.path.join(settings.storage_path, stored_name)
    content = file.file.read()
    if len(content) > settings.MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "文件超过大小限制")
    with open(stored_path, "wb") as f:
        f.write(content)

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
    audit_log.record(db, user_id=user.id, action="upload", target=f"contract:{contract.id}", detail=contract.filename)
    return contract


@router.post("/{contract_id}/parse")
def parse_contract(contract_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    contract = _get_contract(db, contract_id)
    text = extract_text(contract.storage_path)
    elements = extract_elements(text)
    contract.status = "parsed"
    db.commit()
    audit_log.record(db, user_id=user.id, action="parse", target=f"contract:{contract_id}")
    return {"contract_id": contract_id, "elements": elements, "text_length": len(text)}


@router.post("/{contract_id}/audit", response_model=AuditResponse)
def audit_contract_endpoint(
    contract_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("legal", "finance")),
) -> AuditResponse:
    contract = _get_contract(db, contract_id)

    if settings.AUDIT_ASYNC:
        # 异步：派发 Celery 任务，立即返回 task_id，前端轮询任务状态。
        # 冲突项在任务完成后由前端拉取风险时另行获取（此处不阻塞）。
        from app.tasks.audit_tasks import run_contract_audit

        task = run_contract_audit.delay(contract_id)
        contract.status = "auditing"
        db.commit()
        audit_log.record(db, user_id=user.id, action="audit_dispatch", target=f"contract:{contract_id}", detail=f"task:{task.id}")
        return AuditResponse(contract_id=contract_id, task_id=task.id, status="auditing")

    # 同步：本地无 Redis 时直接执行，行为与 Celery 任务一致（共用 run_audit）。
    result = run_audit(db, contract)
    audit_log.record(db, user_id=user.id, action="audit", target=f"contract:{contract_id}", detail=f"risks={result['risk_count']}")
    return AuditResponse(
        contract_id=contract_id,
        status="done",
        risk_count=result["risk_count"],
        cross_checks=[_to_cross_out(c) for c in result["cross_checks"]],
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


@router.get("/{contract_id}/risks", response_model=list[RiskOut])
def get_contract_risks(contract_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[Risk]:
    _get_contract(db, contract_id)
    return db.query(Risk).filter(Risk.contract_id == contract_id).all()


def _get_contract(db: Session, contract_id: int) -> Contract:
    contract = db.query(Contract).filter(Contract.id == contract_id).first()
    if not contract:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "合同不存在")
    return contract
