"""建表初始化。

SQLite 开发期直接 create_all；PostgreSQL 交付期改走 alembic 迁移。
"""
import json
import os

from sqlalchemy import inspect, text

from app.core.config import settings
from app.core.logging import get_logger
from app.core.security import hash_password
from app.db.session import Base, SessionLocal, engine

# 导入模型以注册到 Base.metadata（必须，否则 create_all 建不出表）
from app.models import models  # noqa: F401
from app.models.models import ContractTypeProfile, LookupItem, User

log = get_logger("db")

# 开发期种子账号（生产环境应通过管理后台创建，密码从 env 或首启向导设置）
_SEED_USERS = [
    {"username": "admin",    "password": "admin123",    "role": "admin",    "department": "管理"},
    {"username": "legal",    "password": "legal123",    "role": "legal",    "department": "法务部"},
    {"username": "finance",  "password": "finance123",  "role": "finance",  "department": "财务部"},
    {"username": "business", "password": "business123", "role": "business", "department": "采购中心"},
]

_CONTRACT_TYPE_PROFILE_SEEDS = (
    ("软件开发外包合同", ("软件开发", "软件外包", "系统开发"), ("软件开发", "系统开发", "源代码", "软件外包")),
    ("技术服务合同", ("技术服务", "技术支持", "技术维护"), ("技术服务", "技术支持", "技术维护")),
    ("采购合同", ("采购", "购置"), ("采购", "购置", "供货", "设备")),
    ("销售合同", ("销售", "出售"), ("销售", "出售", "售卖")),
    ("劳动合同", ("劳动",), ("劳动关系", "试用期", "工资")),
    ("租赁合同", ("租赁", "承租", "出租"), ("租赁", "承租", "出租")),
    ("保密协议", ("保密协议",), ("专项保密协议",)),
    ("合作协议", ("合作协议",), ("合作项目",)),
    ("服务协议", ("服务协议",), ("提供服务",)),
    ("框架协议", ("框架",), ("框架合作", "框架采购")),
    ("技术开发合同", ("技术开发", "研发"), ("技术开发", "研发", "技术成果")),
    ("合作合同", ("合作合同",), ("合作项目",)),
    ("服务合同", ("服务合同",), ("提供服务",)),
    ("劳务合同", ("劳务",), ("劳务", "劳务报酬", "劳务人员")),
)


def init_db() -> None:
    # 生产 PostgreSQL 必须由 Alembic 管理，应用进程不得绕过迁移直接建表。
    os.makedirs(settings.storage_path, exist_ok=True)
    if settings.DB_BACKEND == "sqlite":
        Base.metadata.create_all(bind=engine)
        _migrate_dev_columns()
        _seed_contract_type_profiles()
    if settings.APP_ENV != "prod":
        _seed_users()
    log.info("db.init", backend=settings.DB_BACKEND, tables=list(Base.metadata.tables.keys()))


# 开发期轻量补列：create_all 只建表不改已有表结构。SQLite 无 alembic 时，
# 检测到 risks 缺少新增列则 ADD COLUMN，避免删库。生产（PostgreSQL）走 alembic 迁移。
_DEV_COLUMNS = {
    "users": [
        ("authorized_departments_json", "TEXT DEFAULT '[]' NOT NULL"),
    ],
    "risks": [
        ("tier", "VARCHAR(8) DEFAULT 'yellow'"),
        ("rag_sources", "TEXT DEFAULT '[]'"),   # RAG 检索溯源：结构化来源列表
        ("audit_job_id", "INTEGER"),
        ("risk_reason", "TEXT DEFAULT ''"),
        ("evidence_status", "VARCHAR(24) DEFAULT 'unsupported' NOT NULL"),
        ("original_text_verified", "BOOLEAN"),
        ("requires_manual_review", "BOOLEAN DEFAULT 1 NOT NULL"),
        ("support_relation_status", "VARCHAR(16) DEFAULT 'unclear' NOT NULL"),
        ("support_validation_reason", "TEXT DEFAULT '' NOT NULL"),
        ("support_validator_version", "VARCHAR(32) DEFAULT 'unvalidated' NOT NULL"),
        ("claim_id", "VARCHAR(64)"),
        ("claim_status", "VARCHAR(24) DEFAULT 'pending_evidence' NOT NULL"),
        ("source_window_id", "VARCHAR(64)"),
        ("source_clause_ids_json", "TEXT DEFAULT '[]' NOT NULL"),
        ("evidence_ids_json", "TEXT DEFAULT '[]' NOT NULL"),
        ("retrieval_attempts_json", "TEXT DEFAULT '[]' NOT NULL"),
        ("contract_evidence_json", "TEXT DEFAULT '[]' NOT NULL"),
        ("secondary_review_status", "VARCHAR(24) DEFAULT 'not_required' NOT NULL"),
        ("secondary_review_reason", "TEXT DEFAULT '' NOT NULL"),
    ],
    "audit_logs": [("ip", "VARCHAR(64) DEFAULT ''")],
    "contracts": [
        ("elements_json", "TEXT DEFAULT '{}'"),
        ("element_evidence_json", "TEXT DEFAULT '{}' NOT NULL"),
        ("parse_source", "VARCHAR(16) DEFAULT 'native' NOT NULL"),
        ("ocr_confidence", "FLOAT"),
        ("requires_review", "BOOLEAN DEFAULT 0 NOT NULL"),
        ("review_reason", "VARCHAR(255)"),
        ("upload_idempotency_key", "VARCHAR(128)"),
        ("content_sha256", "VARCHAR(64)"),
        ("audit_generation", "INTEGER DEFAULT 0 NOT NULL"),
        ("suggested_type", "VARCHAR(64) DEFAULT '' NOT NULL"),
        ("type_confidence", "FLOAT"),
        ("type_evidence_json", "TEXT DEFAULT '[]' NOT NULL"),
        ("type_confirmed_by", "INTEGER"),
        ("type_confirmed_at", "DATETIME"),
        ("deleted_at", "DATETIME"),
        ("deleted_by", "INTEGER"),
    ],
    "audit_batches": [
        ("dimensions_json", "TEXT DEFAULT '[]'"),
        ("request_fingerprint", "VARCHAR(64) DEFAULT '' NOT NULL"),
    ],
    "audit_batch_items": [
        ("error_code", "VARCHAR(64)"),
        ("result_json", "TEXT DEFAULT '{}' NOT NULL"),
        ("audit_generation", "INTEGER DEFAULT 0 NOT NULL"),
        ("execution_token", "VARCHAR(64)"),
        ("import_item_id", "INTEGER"),
        ("progress", "INTEGER DEFAULT 0 NOT NULL"),
        ("progress_stage", "VARCHAR(24) DEFAULT 'queued' NOT NULL"),
    ],
    "import_batches": [
        ("request_fingerprint", "VARCHAR(64) DEFAULT '' NOT NULL"),
        ("department", "VARCHAR(64) DEFAULT '' NOT NULL"),
    ],
    "llm_call_logs": [
        ("audit_job_id", "INTEGER"),
        ("finish_reason", "VARCHAR(32)"),
        ("window_id", "VARCHAR(64)"),
        ("dimension", "VARCHAR(64) DEFAULT 'all' NOT NULL"),
        ("attempt", "INTEGER DEFAULT 1 NOT NULL"),
        ("validation_status", "VARCHAR(24) DEFAULT 'unknown' NOT NULL"),
        ("error_code", "VARCHAR(64)"),
    ],
    "knowledge_chunks": [
        ("article_number", "VARCHAR(64)"),
        ("version", "VARCHAR(64)"),
        ("effective_date", "DATE"),
        ("expiry_date", "DATE"),
        ("applicable_contract_types", "TEXT DEFAULT '[]'"),
        ("applicable_dimensions", "TEXT DEFAULT '[]'"),
        ("scope_mode", "VARCHAR(16) DEFAULT 'unclassified' NOT NULL"),
        ("embedding_model", "VARCHAR(255)"),
        ("embedding_dimension", "INTEGER"),
        ("content_hash", "VARCHAR(64)"),
        ("legal_article_id", "INTEGER"),
        ("chunk_index", "INTEGER"),
        ("chunk_count", "INTEGER"),
        ("chunk_schema_version", "VARCHAR(32)"),
        ("retrieval_text", "TEXT"),
        ("embedding_signature", "VARCHAR(64)"),
    ],
}

_DEV_INDEXES = {
    "audit_window_runs": ((
        "ix_audit_window_runs_contract_id",
        "CREATE INDEX IF NOT EXISTS ix_audit_window_runs_contract_id ON audit_window_runs(contract_id)",
    ), (
        "ix_audit_window_runs_audit_job_id",
        "CREATE INDEX IF NOT EXISTS ix_audit_window_runs_audit_job_id ON audit_window_runs(audit_job_id)",
    ), (
        "uq_audit_window_runs_identity",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_audit_window_runs_identity ON audit_window_runs("
        "audit_job_id, audit_generation, agent, dimensions_hash, window_id, protocol_version)",
    )),
    "contracts": ((
        "uq_contracts_uploader_upload_idempotency",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_contracts_uploader_upload_idempotency "
        "ON contracts(uploaded_by, upload_idempotency_key)",
    ), (
        "ix_contracts_deleted_at",
        "CREATE INDEX IF NOT EXISTS ix_contracts_deleted_at ON contracts(deleted_at)",
    )),
    "audit_batch_items": ((
        "ix_audit_batch_items_import_item_id",
        "CREATE INDEX IF NOT EXISTS ix_audit_batch_items_import_item_id "
        "ON audit_batch_items(import_item_id)",
    ),),
    "risks": ((
        "ix_risks_audit_job_id",
        "CREATE INDEX IF NOT EXISTS ix_risks_audit_job_id ON risks(audit_job_id)",
    ), (
        "ix_risks_claim_id",
        "CREATE INDEX IF NOT EXISTS ix_risks_claim_id ON risks(claim_id)",
    ),),
    "llm_call_logs": ((
        "ix_llm_call_logs_audit_job_id",
        "CREATE INDEX IF NOT EXISTS ix_llm_call_logs_audit_job_id "
        "ON llm_call_logs(audit_job_id)",
    ),),
}


def _migrate_dev_columns() -> None:
    if settings.DB_BACKEND != "sqlite":
        return
    inspector = inspect(engine)
    with engine.begin() as conn:
        for table, columns in _DEV_COLUMNS.items():
            if not inspector.has_table(table):
                continue
            existing = {c["name"] for c in inspector.get_columns(table)}
            for name, ddl in columns:
                if name not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
                    log.info("db.migrate_column", table=table, column=name)
        for table, indexes in _DEV_INDEXES.items():
            if not inspector.has_table(table):
                continue
            migrated_inspector = inspect(conn)
            table_columns = {
                column["name"]
                for column in migrated_inspector.get_columns(table)
            }
            existing_indexes = {
                index["name"]
                for index in migrated_inspector.get_indexes(table)
            }
            for name, ddl in indexes:
                required_columns = {
                    "ix_audit_window_runs_contract_id": {"contract_id"},
                    "ix_audit_window_runs_audit_job_id": {"audit_job_id"},
                    "uq_audit_window_runs_identity": {
                        "audit_job_id", "audit_generation", "agent", "dimensions_hash",
                        "window_id", "protocol_version",
                    },
                    "uq_contracts_uploader_upload_idempotency": {
                        "uploaded_by", "upload_idempotency_key"
                    },
                    "ix_contracts_deleted_at": {"deleted_at"},
                    "ix_audit_batch_items_import_item_id": {"import_item_id"},
                    "ix_risks_audit_job_id": {"audit_job_id"},
                    "ix_risks_claim_id": {"claim_id"},
                    "ix_llm_call_logs_audit_job_id": {"audit_job_id"},
                }[name]
                if required_columns <= table_columns and name not in existing_indexes:
                    conn.execute(text(ddl))
                    log.info("db.migrate_index", table=table, index=name)
        for table in ("contracts", "audit_batch_items"):
            if inspector.has_table(table) and "status" in {
                column["name"] for column in inspect(conn).get_columns(table)
            }:
                conn.execute(text(
                    f"UPDATE {table} SET status = 'reviewing' WHERE status = 'auditing'"
                ))


def _seed_users() -> None:
    db = SessionLocal()
    try:
        for u in _SEED_USERS:
            if not db.query(User).filter(User.username == u["username"]).first():
                db.add(User(
                    username=u["username"],
                    password_hash=hash_password(u["password"]),
                    role=u["role"],
                    department=u["department"],
                ))
        db.commit()
    finally:
        db.close()


def _seed_contract_type_profiles() -> None:
    db = SessionLocal()
    try:
        lookups = {
            row.value: row
            for row in db.query(LookupItem)
            .filter(LookupItem.category == "contract_type")
            .all()
        }
        for sort_order, (value, aliases, positive_signals) in enumerate(
            _CONTRACT_TYPE_PROFILE_SEEDS
        ):
            lookup = lookups.get(value)
            if lookup is None:
                lookup = LookupItem(
                    category="contract_type",
                    value=value,
                    sort_order=sort_order,
                )
                db.add(lookup)
                db.flush()
                lookups[value] = lookup
            if lookup.contract_type_profile is None:
                lookup.contract_type_profile = ContractTypeProfile(
                    aliases_json=json.dumps(aliases, ensure_ascii=False),
                    positive_signals_json=json.dumps(
                        positive_signals,
                        ensure_ascii=False,
                    ),
                    negative_signals_json="[]",
                )
        db.commit()
    finally:
        db.close()
