"""报表端点：导出 Excel 风险台账。"""
import io
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.models import User
from app.services import audit_log
from app.services.report.exporter import export_risk_ledger

router = APIRouter()

_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.get("/export")
def export_report(
    contract_ids: list[int] | None = Query(default=None, description="按合同 ID 过滤，为空导出全部"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> StreamingResponse:
    data = export_risk_ledger(db, contract_ids)
    audit_log.record(db, user_id=user.id, action="export", target="risk_ledger", detail=f"ids={contract_ids or 'all'}")

    filename = quote("风险台账.xlsx")  # RFC 5987 编码中文文件名
    headers = {"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"}
    return StreamingResponse(io.BytesIO(data), media_type=_XLSX_MIME, headers=headers)
