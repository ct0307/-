"""看板端点：多维统计（风险分布、类别、合同/复核状态）供前端 ECharts。"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.models import User
from app.services.report.exporter import dashboard_summary as _summary

router = APIRouter()


@router.get("/summary")
def dashboard_summary(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    return _summary(db)
