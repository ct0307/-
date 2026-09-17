"""报表端点：导出 Excel 风险台账。"""
import io
from urllib.parse import quote
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from app.api.deps import allowed_departments, get_current_user
from app.db.session import get_db
from app.models.models import User
from app.services import audit_log
from app.services.report.exporter import build_report_snapshot, contracts_metadata, export_report_docx, export_report_xlsx, report_summary

router = APIRouter()

_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class ReportSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    contract_ids: list[Annotated[StrictInt, Field(gt=0)]] | None = Field(default=None, min_length=1, max_length=200)


def _snapshot(db: Session, user: User, contract_ids: list[int] | None) -> dict:
    try:
        # PostgreSQL 使用独立的可重复读事务，避免认证查询已开启的事务影响隔离级别。
        bind = db.get_bind()
        if bind.dialect.name == "postgresql":
            with Session(bind=bind.execution_options(isolation_level="REPEATABLE READ")) as reader:
                return build_report_snapshot(reader, contract_ids, department_scope_for(user))
        return build_report_snapshot(db, contract_ids, department_scope_for(user))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc


@router.post("/preview")
def preview_report(selection: ReportSelection, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    return _snapshot(db, user, selection.contract_ids)


def department_scope_for(user: User) -> set[str] | None:
    """管理员可查看全量，其他角色仅查看当前授权部门集合。"""
    return None if user.role == "admin" else allowed_departments(user)


@router.get("/summary")
def reports_summary(
    range: str = Query(default="month", description="时间分段：month/quarter/year"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """多维报表聚合数据（KPI/趋势/风险分布/部门/Top5），供前端 ReportsView。"""
    return report_summary(db, range, department_scope=department_scope_for(user))


@router.get("/contracts-metadata")
def get_contracts_metadata(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list:
    """合同要素汇总：甲方 / 合同标的 / 收付款节点 + 风险统计，供多维报表「合同要素」区展示。"""
    return contracts_metadata(db, department_scope=department_scope_for(user))


@router.get("/export")
def export_report(
    contract_ids: list[int] | None = Query(default=None, description="按合同 ID 过滤，为空导出全部"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    format: Literal["xlsx", "docx"] = "xlsx",
    report_id: str | None = None,
) -> StreamingResponse:
    snapshot = _snapshot(db, user, contract_ids)
    if report_id is not None and snapshot["report_id"] != report_id:
        raise HTTPException(409, "数据已变化，请重新生成预览后导出")
    data = export_report_docx(snapshot) if format == "docx" else export_report_xlsx(snapshot)
    audit_log.record(db, user_id=user.id, action="export", target="evidence_report", detail=f"ids={snapshot['contract_ids']};report_id={snapshot['report_id']};format={format}")
    db.commit()

    filename = quote(f"合同审查证据报告_{snapshot['report_id'][:12]}.{format}")
    headers = {"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"}
    return StreamingResponse(io.BytesIO(data), media_type=_DOCX_MIME if format == "docx" else _XLSX_MIME, headers=headers)
