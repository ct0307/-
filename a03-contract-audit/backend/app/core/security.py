"""认证与密码：PyJWT + bcrypt。RBAC 角色校验见 api/deps.py。

不用 python-jose(算法混淆 CVE-2024-33663 等 + 停维)和 passlib(停维、与 bcrypt 5.x 不兼容)。
"""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import bcrypt
import jwt

from app.core.config import settings

# bcrypt 仅支持最多 72 字节；拒绝超长输入，避免截断造成密码前缀碰撞。
_BCRYPT_MAX_BYTES = 72


def encode_password(raw: str) -> bytes:
    """校验 UTF-8 字节上限并完整编码，不记录或截断密码。"""
    encoded = raw.encode("utf-8")
    if len(encoded) > _BCRYPT_MAX_BYTES:
        raise ValueError("密码的 UTF-8 编码不能超过 72 字节")
    return encoded


def hash_password(raw: str) -> str:
    return bcrypt.hashpw(encode_password(raw), bcrypt.gensalt()).decode("utf-8")


def verify_password(raw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(encode_password(raw), hashed.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(subject: str, role: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": subject, "role": role, "exp": expire, "jti": uuid4().hex}
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    except jwt.PyJWTError:
        return None
