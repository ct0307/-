"""认证端点：登录发放 JWT。"""
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.core.security import create_access_token, verify_password
from app.db.session import get_db
from app.models.models import User
from app.services import audit_log

router = APIRouter()


def _client_ip(request: Request) -> str:
    """从请求提取客户端 IP（优先 X-Forwarded-For，回落 client.host）。"""
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        return xff.split(",")[0].strip()
    if request.client:
        return request.client.host
    return ""


@router.post("/login")
def login(
    request: Request,
    form: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
) -> dict:
    user = db.query(User).filter(User.username == form.username).first()
    if not user or not verify_password(form.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户名或密码错误")
    token = create_access_token(subject=user.username, role=user.role)
    audit_log.record(
        db, user_id=user.id, action="login",
        target=user.username, ip=_client_ip(request),
    )
    return {"access_token": token, "token_type": "bearer", "role": user.role, "username": user.username, "department": user.department or ""}
