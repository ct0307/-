"""报表端点：导出 Excel 风险台账。"""
import io
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.models import Contract, User
from app.services import audit_log
from app.services.report.exporter import contracts_metadata, export_risk_ledger, report_summary

router = APIRouter()

_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def department_scope_for(user: User) -> str | None:
    """业务用户限定本部门，法务、财务和管理员保持全局报表权限。"""
    return user.department if user.role == "business" else None


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
) -> StreamingResponse:
    department_scope = department_scope_for(user)
    if contract_ids and department_scope:
        accessible_ids = {
            contract_id for (contract_id,) in db.query(Contract.id).filter(
                Contract.id.in_(contract_ids),
                Contract.department == department_scope,
            ).all()
        }
        if accessible_ids != set(contract_ids):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "所选合同包含无权访问的数据")
    data = export_risk_ledger(db, contract_ids, department_scope=department_scope)
    audit_log.record(db, user_id=user.id, action="export", target="risk_ledger", detail=f"ids={contract_ids or 'all'}")

    filename = quote("风险台账.xlsx")  # RFC 5987 编码中文文件名
    headers = {"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"}
    return StreamingResponse(io.BytesIO(data), media_type=_XLSX_MIME, headers=headers)
