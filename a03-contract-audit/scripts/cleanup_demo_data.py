"""仅清理 2026-09-17 用户明确批准的演示记录，先备份后事务执行。"""
import argparse
import ast
import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path

CONTRACT_IDS = tuple(range(3, 15))
RISK_IDS = tuple(range(6, 29))
RECTIFICATION_IDS = tuple(range(1, 7))
CALL_IDS = tuple(range(1, 15))
TARGETS = {"contracts": CONTRACT_IDS, "risks": RISK_IDS,
           "rectifications": RECTIFICATION_IDS, "llm_call_logs": CALL_IDS}


def seeds():
    tree = ast.parse((Path(__file__).resolve().parents[1] / "backend/scripts/seed_demo.py").read_text(encoding="utf-8"))
    result = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in {"_CONTRACTS", "_RECTIFICATIONS", "_LLM_CALLS"}:
                    result[target.id] = ast.literal_eval(node.value)
    return result


def rows(db, table):
    return [dict(row) for row in db.execute(f'SELECT * FROM "{table}" ORDER BY rowid')]


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def inspect_targets(db):
    expected = seeds()
    result = {}
    for table, ids in TARGETS.items():
        result[table] = [r for r in rows(db, table) if r["id"] in ids]
        if len(result[table]) != len(ids):
            raise ValueError(f"清理范围数量改变：{table}")
    for row, seed in zip(result["contracts"], expected["_CONTRACTS"]):
        if row["filename"] != seed[0] or row["storage_path"] != f"storage/demo/{seed[0]}" or row["audit_generation"] != 0:
            raise ValueError("合同种子签名改变")
    if any(r["contract_id"] not in CONTRACT_IDS for r in result["risks"]):
        raise ValueError("风险范围改变")
    fields = ("contract", "risk", "level", "owner", "status", "created", "due", "note")
    for row, seed in zip(result["rectifications"], expected["_RECTIFICATIONS"]):
        wanted = list(seed)
        if row["id"] == 6:
            wanted[4] = "处理中"
        if [row.get(k) for k in fields] != wanted or row.get("risk_id") is not None:
            raise ValueError("整改种子签名改变")
    fields = ("agent", "provider", "model", "prompt_tokens", "completion_tokens", "latency_ms")
    for row, seed in zip(result["llm_call_logs"], expected["_LLM_CALLS"]):
        if tuple(row[k] for k in fields) != tuple(seed[1:]) or row["contract_id"] != CONTRACT_IDS[seed[0]]:
            raise ValueError("模型调用种子签名改变")
    tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    for table in tables:
        columns = [r[1] for r in db.execute(f'PRAGMA table_info("{table}")')]
        if "contract_id" in columns:
            related = [r[0] for r in db.execute(f'SELECT id FROM "{table}" WHERE contract_id BETWEEN 3 AND 14')]
            if set(related) != set(TARGETS.get(table, ())):
                raise ValueError(f"发现未批准的合同依赖：{table}")
        if "risk_id" in columns:
            if db.execute(f'SELECT count(*) FROM "{table}" WHERE risk_id BETWEEN 6 AND 28').fetchone()[0]:
                raise ValueError(f"发现未批准的风险依赖：{table}")
    return result, tables


def cleanup(database: Path, backup_dir: Path):
    if not database.is_file():
        raise ValueError("数据库不存在")
    db = sqlite3.connect(database, timeout=20)
    db.row_factory = sqlite3.Row
    try:
        targets, tables = inspect_targets(db)
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        backup_path = backup_dir / f"before-demo-cleanup-{stamp}.db"
        with sqlite3.connect(backup_path) as backup:
            db.backup(backup)
            backup.row_factory = sqlite3.Row
            assert backup.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            baseline = {t: rows(backup, t) for t in tables}
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("BEGIN IMMEDIATE")
        targets, tables = inspect_targets(db)
        before = {t: rows(db, t) for t in tables}
        existing_violations = {tuple(row) for row in db.execute("PRAGMA foreign_key_check")}
        if fingerprint(before) != fingerprint(baseline):
            raise ValueError("备份后数据库已变化，请重新盘点")
        expected = {t: [r for r in rr if r.get("id") not in TARGETS.get(t, ())] for t, rr in before.items()}
        for table in ("rectifications", "llm_call_logs", "risks", "contracts"):
            ids = TARGETS[table]
            db.execute(f'DELETE FROM "{table}" WHERE id IN ({",".join("?" for _ in ids)})', ids)
        after = {t: rows(db, t) for t in tables}
        if fingerprint(expected) != fingerprint(after):
            raise ValueError("非目标记录发生变化，已回滚")
        current_violations = {tuple(row) for row in db.execute("PRAGMA foreign_key_check")}
        assert not current_violations - existing_violations, "出现新的外键问题，已回滚"
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        manifest = {"backup": str(backup_path), "deleted": targets,
                    "before": {t: len(before[t]) for t in TARGETS},
                    "after": {t: len(after[t]) for t in TARGETS},
                    "unrelated_rows_verified": True,
                    "existing_foreign_key_violations": len(existing_violations),
                    "new_foreign_key_violations": len(current_violations - existing_violations)}
        manifest_path = backup_dir / f"cleanup-manifest-{stamp}.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        db.commit()
        return {k: v for k, v in manifest.items() if k != "deleted"} | {"manifest": str(manifest_path)}
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute-approved-cleanup", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if not args.execute_approved_cleanup:
        raise SystemExit("须先确认精确清理范围，再传 --execute-approved-cleanup")
    print(json.dumps(cleanup(root / "backend/storage/a03_dev.db", root / "outputs/demo-cleanup"), ensure_ascii=False, indent=2))
