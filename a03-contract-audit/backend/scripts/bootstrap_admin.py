"""受控创建首个管理员账号。

脚本只负责新增账号，不参与应用启动，也不会在生产启动时播种演示账号。
可在 backend 目录执行：``python -m scripts.bootstrap_admin``。
"""

from __future__ import annotations

import argparse
import getpass
import sys
from typing import Any, TYPE_CHECKING

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy import text
from sqlalchemy.orm import Session

if TYPE_CHECKING:
    from app.models.models import User

_UNSAFE_CONFIG_MESSAGE = "生产配置不安全，请检查 DEBUG、PostgreSQL、异步任务、JWT 和 Fernet 密钥配置"
_DEFAULT_PASSWORDS = frozenset({
    "admin123", "legal123", "finance123", "business123", "password123456",
    "changeme123456", "change_me_in_production", "123456789012", "administrator",
})


def _load_settings() -> Any:
    # 延迟导入，避免配置校验在命令行错误处理前暴露输入值。
    from app.core.config import settings
    return settings


def SessionLocal() -> Session:
    from app.db.session import SessionLocal as factory
    return factory()


class BootstrapAdminError(RuntimeError):
    """管理员初始化不能继续时抛出的可理解错误。"""


def ensure_bootstrap_allowed(config: Any) -> None:
    """拒绝明显不符合生产要求的初始化配置。"""

    if getattr(config, "APP_ENV", "dev") != "prod":
        return
    from app.core.config import Settings
    try:
        Settings.validate_production_security(config)
    except (ValueError, AttributeError, TypeError) as exc:
        raise BootstrapAdminError(_UNSAFE_CONFIG_MESSAGE) from exc


def create_admin(db: Session, *, username: str, password: str, config: Any = None) -> User:
    """在一个事务中创建管理员，并留下不含密码的审计记录。"""

    ensure_bootstrap_allowed(config if config is not None else _load_settings())
    normalized_username = username.strip()
    if not 1 <= len(normalized_username) <= 64 or any(ord(char) < 32 for char in normalized_username):
        raise BootstrapAdminError("管理员用户名必须为 1 至 64 个字符")
    if len(password) < 12 or len(password.encode("utf-8")) > 72:
        raise BootstrapAdminError("管理员密码至少 12 个字符，且不得超过 72 个 UTF-8 字节")
    if password.casefold() in _DEFAULT_PASSWORDS:
        raise BootstrapAdminError("管理员密码不能使用默认密码")

    from app.core.security import hash_password
    from app.models.models import User
    from app.services import audit_log
    try:
        # 两个不同用户名也必须争用同一事务锁，避免并发创建多个首个管理员。
        dialect = db.get_bind().dialect.name
        if dialect == "postgresql":
            db.execute(text("SELECT pg_advisory_xact_lock(:lock_key)"), {"lock_key": 0x41303341444D494E})
        elif dialect == "sqlite":
            db.connection().exec_driver_sql("BEGIN IMMEDIATE")
        else:
            raise BootstrapAdminError("管理员初始化不支持当前数据库类型")
        if db.query(User).filter(User.username == normalized_username).first() is not None:
            raise BootstrapAdminError("用户名已存在，拒绝覆盖账号")
        if db.query(User).filter(User.role == "admin").first() is not None:
            raise BootstrapAdminError("管理员已存在，拒绝重复初始化")
        user = User(
            username=normalized_username,
            password_hash=hash_password(password),
            role="admin",
            department="管理",
        )
        db.add(user)
        db.flush()
        audit_log.record(
            db,
            user_id=user.id,
            action="bootstrap_admin",
            target=user.username,
            detail="通过受控初始化脚本创建管理员",
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise BootstrapAdminError("用户名已存在，初始化已回滚") from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise BootstrapAdminError("数据库操作失败，请检查连接和迁移状态；初始化未完成") from exc
    except Exception:
        db.rollback()
        raise
    return user


def _parser() -> argparse.ArgumentParser:
    class SafeArgumentParser(argparse.ArgumentParser):
        def error(self, message: str) -> None:
            # argparse 默认回显未知参数，可能包含误传的密码。
            self.print_usage(sys.stderr)
            self.exit(2, "参数无效；仅支持 --username，密码必须通过隐藏输入提供\n")

    parser = SafeArgumentParser(description="创建首个生产管理员账号", allow_abbrev=False)
    parser.add_argument("--username", help="管理员用户名；省略时交互输入")
    return parser


def main(argv: list[str] | None = None) -> int:
    """命令行入口；密码始终由 getpass 读取，不接受命令行参数。"""

    args = _parser().parse_args(argv)
    try:
        config = _load_settings()
        ensure_bootstrap_allowed(config)
        username = (args.username or input("管理员用户名：")).strip()
        password = getpass.getpass("管理员密码：")
        confirmation = getpass.getpass("再次输入管理员密码：")
        if password != confirmation:
            print("两次输入的密码不一致", file=sys.stderr)
            return 2
        with SessionLocal() as db:
            create_admin(db, username=username, password=password, config=config)
    except BootstrapAdminError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except SQLAlchemyError:
        print("数据库连接失败，请检查连接和迁移状态", file=sys.stderr)
        return 1
    except (ValueError, TypeError):
        print(_UNSAFE_CONFIG_MESSAGE, file=sys.stderr)
        return 1
    except (EOFError, KeyboardInterrupt):
        print("管理员初始化已取消", file=sys.stderr)
        return 2
    except Exception:
        print("管理员初始化失败，请检查配置和迁移状态", file=sys.stderr)
        return 1
    print(f"管理员账号已创建：{username}")
    return 0


if __name__ == "__main__":  # pragma: no cover - 命令行壳由集成环境调用
    raise SystemExit(main())
