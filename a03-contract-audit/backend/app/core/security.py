"""认证与密码：PyJWT + bcrypt。RBAC 角色校验见 api/deps.py。

不用 python-jose(算法混淆 CVE-2024-33663 等 + 停维)和 passlib(停维、与 bcrypt 5.x 不兼容)。
"""
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.core.config import settings

# bcrypt 单次最多处理 72 字节，超出部分会被静默截断。
# 直接截断到 72 字节，避免不同长度密码碰撞到同一哈希。
_BCRYPT_MAX_BYTES = 72


def _truncate(raw: str) -> bytes:
    return raw.encode("utf-8")[:_BCRYPT_MAX_BYTES]


def hash_password(raw: str) -> str:
    return bcrypt.hashpw(_truncate(raw), bcrypt.gensalt()).decode("utf-8")


def verify_password(raw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_truncate(raw), hashed.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(subject: str, role: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": subject, "role": role, "exp": expire}
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    except jwt.PyJWTError:
        return None
