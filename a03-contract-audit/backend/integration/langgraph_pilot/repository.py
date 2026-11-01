"""独立 SQLite 业务替身：身份围栏、调用账本、人工授权和幂等发布。"""
from contextlib import contextmanager
from dataclasses import asdict
import json
from pathlib import Path
import sqlite3
import time

from .state import AccessDenied, FlowIssue, StaleRun, fingerprint


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


class PilotStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.transaction() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS authority (
                    contract_id INTEGER, job_id INTEGER, identity TEXT NOT NULL, token TEXT NOT NULL,
                    PRIMARY KEY(contract_id, job_id));
                CREATE TABLE IF NOT EXISTS runs (thread TEXT PRIMARY KEY, limits TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS calls (
                    thread TEXT, call_key TEXT, reserved INTEGER NOT NULL, charged INTEGER NOT NULL,
                    status TEXT NOT NULL, response TEXT, PRIMARY KEY(thread, call_key));
                CREATE TABLE IF NOT EXISTS grants (principal TEXT, contract_id INTEGER,
                    PRIMARY KEY(principal, contract_id));
                CREATE TABLE IF NOT EXISTS decisions (
                    thread TEXT PRIMARY KEY, marker TEXT NOT NULL, principal TEXT, decision TEXT);
                CREATE TABLE IF NOT EXISTS publications (
                    thread TEXT NOT NULL, contract_id INTEGER, job_id INTEGER, generation INTEGER,
                    snapshot_hash TEXT NOT NULL, snapshot TEXT NOT NULL,
                    PRIMARY KEY(contract_id,job_id,generation));
                CREATE TABLE IF NOT EXISTS events (
                    thread TEXT, sequence INTEGER, node TEXT NOT NULL, kind TEXT NOT NULL,
                    timestamp REAL NOT NULL, completed_count INTEGER NOT NULL,
                    PRIMARY KEY(thread, sequence));
                CREATE TABLE IF NOT EXISTS checkpoint_events (
                    thread TEXT, checkpoint_id TEXT, PRIMARY KEY(thread,checkpoint_id));
            ''')

    @contextmanager
    def transaction(self):
        db = sqlite3.connect(str(self.path), timeout=10)
        db.row_factory = sqlite3.Row
        try:
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def register(self, identity, token):
        with self.transaction() as db:
            db.execute('INSERT OR IGNORE INTO authority VALUES (?,?,?,?)',
                       (identity.contract_id, identity.job_id, encoded(asdict(identity)), token))
            self._check(db, identity, token)

    def replace_authority(self, identity, token):
        """隔离测试模拟新代次或执行权交接；不是正式业务更新入口。"""
        with self.transaction() as db:
            db.execute('UPDATE authority SET identity=?,token=? WHERE contract_id=? AND job_id=?',
                       (encoded(asdict(identity)), token, identity.contract_id, identity.job_id))

    @staticmethod
    def _check(db, identity, token):
        row = db.execute('SELECT identity,token FROM authority WHERE contract_id=? AND job_id=?',
                         (identity.contract_id, identity.job_id)).fetchone()
        if row is None or row['identity'] != encoded(asdict(identity)) or row['token'] != token:
            raise StaleRun('任务身份、知识版本或执行权已失效')

    def check(self, identity, token):
        with self.transaction() as db:
            self._check(db, identity, token)

    def bind_limits(self, identity, token, limits):
        with self.transaction() as db:
            self._check(db, identity, token)
            previous = db.execute('SELECT limits FROM runs WHERE thread=?', (identity.thread_id,)).fetchone()
            text = encoded(asdict(limits))
            if previous is not None and previous['limits'] != text:
                raise StaleRun('恢复不得变更预算或延长时限')
            db.execute('INSERT OR IGNORE INTO runs VALUES (?,?)', (identity.thread_id, text))

    @staticmethod
    def _budget(db, thread):
        row = db.execute('SELECT COUNT(*) calls,COALESCE(SUM(charged),0) charged,'
                         'COALESCE(SUM(CASE WHEN status="pending" THEN reserved ELSE 0 END),0) reserved,'
                         'COALESCE(SUM(CASE WHEN status="pending" THEN 1 ELSE 0 END),0) pending '
                         'FROM calls WHERE thread=?', (thread,)).fetchone()
        return dict(row)

    def budget(self, identity):
        with self.transaction() as db:
            return self._budget(db, identity.thread_id)

    def reserve(self, identity, token, key, estimate, limits, now):
        with self.transaction() as db:
            self._check(db, identity, token)
            row = db.execute('SELECT * FROM calls WHERE thread=? AND call_key=?',
                             (identity.thread_id, key)).fetchone()
            if row is not None:
                if row['status'] == 'pending':
                    raise FlowIssue('UNCERTAIN_EXTERNAL_CALL')
                return json.loads(row['response'])
            if now >= limits.deadline:
                raise FlowIssue('AUDIT_DEADLINE_EXCEEDED')
            usage = self._budget(db, identity.thread_id)
            if usage['calls'] >= limits.max_calls or usage['charged'] + usage['reserved'] + estimate > limits.max_tokens:
                raise FlowIssue('AUDIT_BUDGET_EXHAUSTED')
            db.execute('INSERT INTO calls VALUES (?,?,?,?,?,NULL)',
                       (identity.thread_id, key, estimate, 0, 'pending'))
            return None

    def settle(self, identity, token, key, result):
        with self.transaction() as db:
            self._check(db, identity, token)
            row = db.execute('SELECT reserved,status FROM calls WHERE thread=? AND call_key=?',
                             (identity.thread_id, key)).fetchone()
            if row is None or row['status'] != 'pending':
                raise StaleRun('缺少有效的调用预留')
            db.execute('UPDATE calls SET charged=?,status="complete",response=? WHERE thread=? AND call_key=?',
                       (max(row['reserved'], result.usage_tokens), encoded(result.payload), identity.thread_id, key))

    def event(self, identity, token, node, kind, completed_count=None):
        with self.transaction() as db:
            self._check(db, identity, token)
            self._append_event(db, identity.thread_id, node, kind, completed_count)

    @staticmethod
    def _append_event(db, thread, node, kind, completed_count=None):
        previous = db.execute('SELECT sequence,completed_count FROM events WHERE thread=? ORDER BY sequence DESC LIMIT 1',
                              (thread,)).fetchone()
        seq = previous['sequence'] + 1 if previous is not None else 1
        count = max(previous['completed_count'] if previous is not None else 0, completed_count or 0)
        db.execute('INSERT INTO events VALUES (?,?,?,?,?,?)', (thread, seq, node, kind, time.time(), count))

    def record_checkpoint(self, identity, token, checkpoint):
        values = checkpoint.get('channel_values', {})
        if not values.get('last_node'):
            return
        with self.transaction() as db:
            self._check(db, identity, token)
            inserted = db.execute('INSERT OR IGNORE INTO checkpoint_events VALUES (?,?)',
                                  (identity.thread_id, checkpoint['id'])).rowcount
            if inserted:
                self._append_event(db, identity.thread_id, values['last_node'], 'committed', len(values.get('candidates', [])))

    def events(self, identity):
        with self.transaction() as db:
            return [dict(row) for row in db.execute('SELECT sequence,node,kind,timestamp,completed_count FROM events WHERE thread=? ORDER BY sequence',
                                                   (identity.thread_id,))]

    def grant(self, principal, contract_id):
        with self.transaction() as db:
            db.execute('INSERT OR IGNORE INTO grants VALUES (?,?)', (principal, contract_id))

    def set_interrupt(self, identity, token, marker):
        with self.transaction() as db:
            self._check(db, identity, token)
            row = db.execute('SELECT marker FROM decisions WHERE thread=?', (identity.thread_id,)).fetchone()
            if row is not None and row['marker'] != marker:
                raise AccessDenied('中断标识不匹配')
            db.execute('INSERT OR IGNORE INTO decisions(thread,marker) VALUES (?,?)', (identity.thread_id, marker))

    def decide(self, identity, token, principal, marker, decision):
        with self.transaction() as db:
            self._check(db, identity, token)
            if decision not in {'approve', 'reject'}:
                raise AccessDenied('未知人工决定')
            permission = db.execute('SELECT 1 FROM grants WHERE principal=? AND contract_id=?',
                                    (principal, identity.contract_id)).fetchone()
            row = db.execute('SELECT * FROM decisions WHERE thread=?', (identity.thread_id,)).fetchone()
            if not permission or row is None or row['marker'] != marker:
                raise AccessDenied('无恢复权限或中断标识不匹配')
            if row['decision'] is not None and (row['decision'] != decision or row['principal'] != principal):
                raise AccessDenied('已经记录的人工决定不能覆盖')
            db.execute('UPDATE decisions SET principal=?,decision=? WHERE thread=?',
                       (principal, decision, identity.thread_id))

    def decision(self, identity, token, marker):
        with self.transaction() as db:
            self._check(db, identity, token)
            row = db.execute('SELECT decision FROM decisions WHERE thread=? AND marker=?',
                             (identity.thread_id, marker)).fetchone()
            if row is None or row['decision'] is None:
                raise AccessDenied('人工决定尚未有效记录')
            return row['decision']

    def publish(self, identity, token, snapshot):
        with self.transaction() as db:
            self._check(db, identity, token)
            business_key = (identity.contract_id, identity.job_id, identity.generation)
            row = db.execute('SELECT snapshot_hash FROM publications WHERE contract_id=? AND job_id=? AND generation=?', business_key).fetchone()
            digest = fingerprint(snapshot)
            if row is not None and row['snapshot_hash'] != digest:
                raise StaleRun('同一运行不得发布不同快照')
            db.execute('INSERT OR IGNORE INTO publications VALUES (?,?,?,?,?,?)',
                       (identity.thread_id, *business_key, digest, encoded(snapshot)))

    def publication_count(self, identity):
        with self.transaction() as db:
            return db.execute('SELECT COUNT(*) FROM publications WHERE contract_id=? AND job_id=? AND generation=?',
                              (identity.contract_id, identity.job_id, identity.generation)).fetchone()[0]
