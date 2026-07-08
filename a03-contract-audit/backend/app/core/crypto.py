"""合同文件加密/解密：企业数据安全硬约束。

使用 Fernet（AES-128-CBC + HMAC-SHA256），密钥由 FILE_ENCRYPT_KEY 环境变量提供。
- 密钥为空（开发/演示模式）：直接读写明文，向后兼容。
- 密钥已设置：上传即加密落盘，读取即解密后处理，合同内容不以明文存储。

生成密钥：
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

安全注意：
- 密钥仅通过 .env / 环境变量传入，绝不硬编码。
- 生产环境建议将密钥托管到密钥管理服务（KMS）。
"""
from app.core.logging import get_logger

log = get_logger("crypto")


def _get_fernet():
    """懒加载 Fernet 实例，密钥为空时返回 None（明文模式）。"""
    from app.core.config import settings
    key = settings.FILE_ENCRYPT_KEY.strip()
    if not key:
        return None
    try:
        from cryptography.fernet import Fernet
        return Fernet(key.encode() if isinstance(key, str) else key)
    except Exception as exc:
        log.error("crypto.key_invalid", error=str(exc))
        raise ValueError(f"FILE_ENCRYPT_KEY 无效，请重新生成：{exc}") from exc


def encrypt_bytes(data: bytes) -> bytes:
    """加密文件内容。密钥未设置时原样返回（明文模式）。"""
    f = _get_fernet()
    if f is None:
        return data
    encrypted = f.encrypt(data)
    log.debug("crypto.encrypt", original_len=len(data), encrypted_len=len(encrypted))
    return encrypted


def decrypt_bytes(data: bytes) -> bytes:
    """解密文件内容。密钥未设置时原样返回（明文模式）。"""
    f = _get_fernet()
    if f is None:
        return data
    try:
        decrypted = f.decrypt(data)
        log.debug("crypto.decrypt", decrypted_len=len(decrypted))
        return decrypted
    except Exception as exc:
        log.error("crypto.decrypt_failed", error=str(exc)[:120])
        raise ValueError("合同文件解密失败，可能密钥不匹配或文件损坏") from exc


def is_encryption_enabled() -> bool:
    from app.core.config import settings
    return bool(settings.FILE_ENCRYPT_KEY.strip())
