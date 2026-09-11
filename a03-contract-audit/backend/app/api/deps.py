"""API 依赖：当前用户解析 + RBAC 角色校验。"""
from collections.abc import Callable
import json

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.db.session import get_db
from app.models.models import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")

# 角色体系：与前端一致（业务/法务/财务/管理员）
ROLES = {"business", "legal", "finance", "admin"}


def allowed_departments(user: User) -> set[str]:
    """返回用户可以操作的数据归属部门。"""

    if user.role == "business":
        return {user.department} if user.department else set()
    try:
        configured = json.loads(user.authorized_departments_json or "[]")
    except (TypeError, ValueError):
        configured = []
    if not isinstance(configured, list):
        configured = []
    return {user.department, *(value for value in configured if isinstance(value, str))} - {""}


def require_department_access(user: User, department: str) -> None:
    """拒绝跨越用户授权集合的数据归属部门操作。"""

    if user.role == "admin":
        return
    if department not in allowed_departments(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "无权操作该数据归属部门")


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    payload = decode_access_token(token)
    if not payload or "sub" not in payload:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "无效或过期的凭证")
    user = db.query(User).filter(User.username == payload["sub"]).first()
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户不存在")
    return user


def require_roles(*allowed: str) -> Callable:
    """RBAC 守卫：限定端点可访问角色。"""

    def _guard(user: User = Depends(get_current_user)) -> User:
        if user.role != "admin" and user.role not in allowed:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "无权访问此资源")
        return user

    return _guard
