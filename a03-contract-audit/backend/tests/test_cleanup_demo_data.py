"""演示清理必须按签名识别，且备份完整、无关记录不变。"""
import importlib.util
import sqlite3
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/cleanup_demo_data.py"


def load_cleaner():
    assert SCRIPT.exists(), "缺少经确认范围的清理工具"
    spec = importlib.util.spec_from_file_location("cleanup_demo", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cleanup_is_exact_and_recoverable(tmp_path):
    module = load_cleaner()
    path = tmp_path / "test.db"
    db = sqlite3.connect(path)
    db.executescript("""
        CREATE TABLE contracts(id INTEGER PRIMARY KEY,filename TEXT,storage_path TEXT,audit_generation INTEGER);
        CREATE TABLE risks(id INTEGER PRIMARY KEY,contract_id INTEGER REFERENCES contracts(id));
        CREATE TABLE rectifications(id INTEGER PRIMARY KEY,contract TEXT,risk TEXT,risk_id INTEGER);
        CREATE TABLE llm_call_logs(id INTEGER PRIMARY KEY,contract_id INTEGER REFERENCES contracts(id), agent TEXT, provider TEXT,model TEXT,prompt_tokens INTEGER,completion_tokens INTEGER,latency_ms INTEGER);
        CREATE TABLE audit_batch_items(id INTEGER PRIMARY KEY,contract_id INTEGER REFERENCES contracts(id));
    """)
    db.execute("INSERT INTO contracts VALUES(90,'真实.pdf','storage/real.pdf',1)")
    db.commit()
    db.close()
    with pytest.raises(ValueError, match="范围|数量|签名"):
        module.cleanup(path, tmp_path / "backup")
    with sqlite3.connect(path) as check:
        assert check.execute("SELECT filename FROM contracts").fetchall() == [("真实.pdf",)]


def test_inventory_targets_have_no_name_only_matching():
    module = load_cleaner()
    assert module.CONTRACT_IDS == tuple(range(3, 15))
    assert module.RISK_IDS == tuple(range(6, 29))
    assert module.RECTIFICATION_IDS == tuple(range(1, 7))
    assert module.CALL_IDS == tuple(range(1, 15))


def test_approved_seed_cleanup_preserves_real_rows_and_backup(tmp_path):
    module = load_cleaner()
    data = module.seeds()
    path = tmp_path / "seed.db"
    with sqlite3.connect(path) as db:
        db.executescript("""
        CREATE TABLE contracts(id INTEGER PRIMARY KEY,filename TEXT,storage_path TEXT,audit_generation INTEGER);
        CREATE TABLE risks(id INTEGER PRIMARY KEY,contract_id INTEGER REFERENCES contracts(id));
        CREATE TABLE rectifications(id INTEGER PRIMARY KEY,contract TEXT,risk TEXT,level TEXT,owner TEXT,status TEXT,created TEXT,due TEXT,note TEXT,risk_id INTEGER);
        CREATE TABLE llm_call_logs(id INTEGER PRIMARY KEY,contract_id INTEGER REFERENCES contracts(id),agent TEXT,provider TEXT,model TEXT,prompt_tokens INTEGER,completion_tokens INTEGER,latency_ms INTEGER);
        CREATE TABLE audit_batch_items(id INTEGER PRIMARY KEY,contract_id INTEGER REFERENCES contracts(id));
        """)
        for cid, seed in zip(module.CONTRACT_IDS, data['_CONTRACTS']):
            db.execute('INSERT INTO contracts VALUES(?,?,?,0)', (cid, seed[0], 'storage/demo/' + seed[0]))
        for rid in module.RISK_IDS:
            db.execute('INSERT INTO risks VALUES(?,3)', (rid,))
        for rid, seed in zip(module.RECTIFICATION_IDS, data['_RECTIFICATIONS']):
            row = list(seed)
            if rid == 6:
                row[4] = '处理中'
            db.execute('INSERT INTO rectifications VALUES(?,?,?,?,?,?,?,?,?,NULL)', (rid, *row))
        for lid, seed in zip(module.CALL_IDS, data['_LLM_CALLS']):
            db.execute('INSERT INTO llm_call_logs VALUES(?,?,?,?,?,?,?,?)', (lid, module.CONTRACT_IDS[seed[0]], *seed[1:]))
        db.execute("INSERT INTO contracts VALUES(90,'真实.pdf','storage/real.pdf',1)")
        db.execute('INSERT INTO audit_batch_items VALUES(1,90)')
        db.execute('INSERT INTO audit_batch_items VALUES(2,999)')
    result = module.cleanup(path, tmp_path / 'backups')
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT id FROM contracts').fetchall() == [(90,)]
        assert db.execute('SELECT * FROM audit_batch_items').fetchall() == [(1, 90), (2, 999)]
    with sqlite3.connect(result['backup']) as db:
        assert db.execute('SELECT count(*) FROM contracts').fetchone()[0] == 13
    assert result['unrelated_rows_verified'] is True
    assert result['existing_foreign_key_violations'] == 1
    assert result['new_foreign_key_violations'] == 0
