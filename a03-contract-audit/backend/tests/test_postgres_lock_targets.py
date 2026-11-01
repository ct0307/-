from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Query, Session

from app.services.audit.runner import _locked_item


def test_locked_item_sql_locks_only_batch_item_not_nullable_join(monkeypatch):
    # 编译真实查询，复现 PostgreSQL 不允许锁定 LEFT JOIN 可空侧的问题。
    monkeypatch.setattr(Query, 'one', lambda query: str(query.statement.compile(dialect=postgresql.dialect())))
    with Session() as db:
        sql = _locked_item(db, contract_id=1, batch_item_id=1)
    assert 'LEFT OUTER JOIN contracts' in sql
    assert sql.endswith('FOR UPDATE OF audit_batch_items')
