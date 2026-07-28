"""将现有 SQLite 业务数据事务化迁移到已完成 Alembic 升级的 PostgreSQL。"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Sequence

from sqlalchemy import Engine, Table, create_engine, func, inspect, select, text

from app.db.session import Base
from app.models import models  # noqa: F401


def _validate_target_schema(target: Engine, tables: Sequence[Table]) -> None:
    inspector = inspect(target)
    missing = [table.name for table in tables if not inspector.has_table(table.name)]
    if missing:
        raise RuntimeError(
            "目标库缺少表，请先执行 alembic upgrade head: " + ", ".join(missing)
        )


def _reset_postgres_sequences(connection, tables: Sequence[Table]) -> None:
    if connection.dialect.name != "postgresql":
        return
    quote = connection.dialect.identifier_preparer.quote
    for table in tables:
        primary_keys = list(table.primary_key.columns)
        if len(primary_keys) != 1:
            continue
        column = primary_keys[0]
        if not hasattr(column.type, "python_type") or column.type.python_type is not int:
            continue
        table_name = quote(table.name)
        column_name = quote(column.name)
        connection.execute(
            text(
                "SELECT setval(pg_get_serial_sequence(:table_name, :column_name), "
                f"COALESCE(MAX({column_name}), 1), MAX({column_name}) IS NOT NULL) "
                f"FROM {table_name}"
            ),
            {"table_name": table.name, "column_name": column.name},
        )


def migrate_data(
    source: Engine,
    target: Engine,
    *,
    tables: Sequence[Table] | None = None,
    batch_size: int = 1000,
) -> dict[str, int]:
    """复制全部指定表并核对数量；异常时目标事务整体回滚。"""
    selected = list(tables or Base.metadata.sorted_tables)
    if batch_size < 1:
        raise ValueError("batch_size 必须大于 0")
    _validate_target_schema(target, selected)

    counts: dict[str, int] = {}
    with source.connect() as source_connection, target.begin() as target_connection:
        for table in selected:
            existing = target_connection.scalar(select(func.count()).select_from(table))
            if existing:
                raise RuntimeError(f"目标表 {table.name} 非空，已取消迁移")

        for table in selected:
            source_count = int(
                source_connection.scalar(select(func.count()).select_from(table)) or 0
            )
            result = source_connection.execute(select(table)).mappings()
            for rows in result.partitions(batch_size):
                target_connection.execute(table.insert(), [dict(row) for row in rows])

            target_count = int(
                target_connection.scalar(select(func.count()).select_from(table)) or 0
            )
            if target_count != source_count:
                raise RuntimeError(
                    f"表 {table.name} 数量核对失败: source={source_count}, target={target_count}"
                )
            counts[table.name] = source_count

        _reset_postgres_sequences(target_connection, selected)
    return counts


def _source_counts(source: Engine) -> dict[str, int]:
    with source.connect() as connection:
        return {
            table.name: int(
                connection.scalar(select(func.count()).select_from(table)) or 0
            )
            for table in Base.metadata.sorted_tables
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sqlite-path", required=True, type=Path)
    parser.add_argument(
        "--postgres-url-env",
        default="A03_POSTGRES_URL",
        help="保存 PostgreSQL SQLAlchemy URL 的环境变量名",
    )
    parser.add_argument("--execute", action="store_true", help="执行迁移；省略时仅统计源库")
    args = parser.parse_args()

    sqlite_path = args.sqlite_path.resolve()
    if not sqlite_path.is_file():
        parser.error(f"SQLite 文件不存在: {sqlite_path}")
    source = create_engine(f"sqlite:///{sqlite_path.as_posix()}")
    try:
        if not args.execute:
            for table_name, count in _source_counts(source).items():
                print(f"{table_name}: {count}")
            print("仅完成源库统计；添加 --execute 才会写入目标库。")
            return 0

        target_url = os.environ.get(args.postgres_url_env, "")
        if not target_url:
            parser.error(f"环境变量 {args.postgres_url_env} 未设置")
        target = create_engine(target_url)
        try:
            if target.dialect.name != "postgresql":
                parser.error("目标 URL 必须使用 PostgreSQL 驱动")
            counts = migrate_data(source, target)
        finally:
            target.dispose()
    finally:
        source.dispose()

    for table_name, count in counts.items():
        print(f"{table_name}: {count}")
    print("迁移完成，所有表数量核对一致。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
