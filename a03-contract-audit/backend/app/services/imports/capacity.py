"""以原始明文字节数计算导入容量，沿用审计表保存元数据。"""

import json
import hashlib
from pathlib import Path
from contextlib import contextmanager
from collections.abc import Iterator

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.crypto import decrypt_bytes, is_encryption_enabled
from app.models.models import AuditLog, ImportBatch, ImportBatchItem


@contextmanager
def serialize_append_transaction(db: Session) -> Iterator[None]:
    """SQLite 先取得写事务，再读容量；PostgreSQL 继续使用批次行锁。"""
    sqlite = db.get_bind().dialect.name == "sqlite"
    try:
        if sqlite:
            # 认证依赖可能已开启只读事务；结束它并使 ORM 缓存失效，重新读取权限和批次。
            db.rollback()
            db.connection().exec_driver_sql("BEGIN IMMEDIATE")
        yield
    except Exception:
        db.rollback()
        raise
    finally:
        # 重放和鉴权/容量拒绝也必须释放写锁，正常结果在返回前已转换为响应模型。
        if sqlite:
            db.rollback()


def capacity_error(code: str, message: str) -> HTTPException:
    return HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, {"code": code, "message": message})


def record_upload_sizes(db: Session, items: list[ImportBatchItem], sizes: list[int], *, user_id: int) -> None:
    """包括失败项在内记录上传原始大小，提交由导入事务统一负责。"""
    db.flush()
    for item, size in zip(items, sizes, strict=True):
        db.add(AuditLog(
            user_id=user_id,
            action="import_item_capacity",
            target=f"import-item:{item.id}",
            detail=json.dumps({"version": 1, "plaintext_bytes": size}, separators=(",", ":")),
        ))


def _unknown_capacity() -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, {
        "code": "IMPORT_BATCH_CAPACITY_UNKNOWN",
        "message": "无法核实旧收件箱的原始文件大小，请恢复文件或新建收件箱后上传",
    })


def existing_batch_bytes(db: Session, batch: ImportBatch) -> int:
    """优先审计元数据；旧项按明文/解密结果计数，无法核实时拒绝追加。"""
    items = [item for item in batch.items if item.status != "deleted"]
    targets = [f"import-item:{item.id}" for item in items]
    records = db.query(AuditLog).filter(
        AuditLog.action == "import_item_capacity", AuditLog.target.in_(targets),
    ).all() if targets else []
    sizes: dict[str, int] = {}
    for record in records:
        try:
            size = json.loads(record.detail)["plaintext_bytes"]
        except (ValueError, TypeError, KeyError):
            raise _unknown_capacity() from None
        if type(size) is not int or size < 0 or (record.target in sizes and sizes[record.target] != size):
            raise _unknown_capacity()
        sizes[record.target] = size

    total = 0
    for item in items:
        target = f"import-item:{item.id}"
        if target in sizes:
            total += sizes[target]
            continue
        if item.contract is None:
            raise _unknown_capacity()
        try:
            stored = Path(item.contract.storage_path).read_bytes()
            # 旧开发环境允许明文；Fernet 密文必须解密后才能得到原始大小。
            if stored.startswith(b"gAAAA"):
                if not is_encryption_enabled():
                    raise _unknown_capacity()
                stored = decrypt_bytes(stored)
            if not stored or (item.contract.content_sha256 and hashlib.sha256(stored).hexdigest() != item.contract.content_sha256):
                raise _unknown_capacity()
            total += len(stored)
        except (OSError, ValueError):
            raise _unknown_capacity() from None
    return total
