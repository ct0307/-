"""看板端点：多维统计（风险分布、类别、合同/复核状态）供前端 ECharts。"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import allowed_departments, get_current_user
from app.db.session import get_db
from app.models.models import User
from app.services.report.exporter import dashboard_summary as _summary

router = APIRouter()


@router.get("/summary")
def dashboard_summary(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    department_scope = None if user.role == "admin" else allowed_departments(user)
    return _summary(db, department_scope=department_scope)
