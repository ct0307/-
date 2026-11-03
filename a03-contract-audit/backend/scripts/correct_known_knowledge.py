"""预览或修复已确认的两条旧知识错误；默认不写入，必须显式指定数据库。"""
import argparse
import json
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.models.models import User
from app.services.rag.known_corrections import correct_known_rules


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, required=True, help='现有SQLite数据库路径')
    parser.add_argument('--actor', default='admin', help='登记审计的现有管理员用户名')
    parser.add_argument('--apply', action='store_true', help='实际应用；省略时仅预览')
    args = parser.parse_args()
    path = args.database.resolve()
    if not path.is_file():
        parser.error('数据库不存在，不会创建空库')
    # 预览使用SQLite只读连接，防止无意写入。
    url = f'sqlite:///{path.as_posix()}' if args.apply else f'sqlite:///{path.as_uri()}?mode=ro&uri=true'
    engine = create_engine(url)
    try:
        with Session(engine) as db:
            actor = db.query(User).filter_by(username=args.actor, role='admin').first()
            if actor is None:
                parser.error('找不到指定的管理员，无法登记纠错审计')
            changes = correct_known_rules(db, actor, apply=args.apply)
            print(json.dumps(dict(mode='applied' if args.apply else 'preview', count=len(changes), changes=changes), ensure_ascii=False, indent=2))
    finally:
        engine.dispose()


if __name__ == '__main__':
    main()
