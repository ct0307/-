"""ORM 模型定义。骨架：定义核心表结构，字段可随业务细化。

企业交付要点：合同敏感数据、完整审核链、审计日志留痕。
"""
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    false,
    func,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), default="business")  # business/legal/finance/admin
    department: Mapped[str] = mapped_column(String(64), default="")
    authorized_departments_json: Mapped[str] = mapped_column(Text, default="[]", server_default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Contract(Base):
    __tablename__ = "contracts"
    __table_args__ = (
        UniqueConstraint(
            "uploaded_by",
            "upload_idempotency_key",
            name="uq_contracts_uploader_upload_idempotency",
        ),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    filename: Mapped[str] = mapped_column(String(255))
    storage_path: Mapped[str] = mapped_column(String(512))  # 私有化本地存储路径
    contract_type: Mapped[str] = mapped_column(String(64), default="")
    suggested_type: Mapped[str] = mapped_column(String(64), default="", server_default="")
    type_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    type_evidence_json: Mapped[str] = mapped_column(Text, default="[]", server_default="[]")
    type_confirmed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    type_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    department: Mapped[str] = mapped_column(String(64), default="")  # 访问隔离维度
    status: Mapped[str] = mapped_column(String(32), default="uploaded")  # uploaded/parsed/auditing/done
    uploaded_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    upload_idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    content_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    audit_generation: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    elements_json: Mapped[str] = mapped_column(Text, default="{}")  # JSON：解析要素（甲方/标的/收付款节点等）
    element_evidence_json: Mapped[str] = mapped_column(
        Text, default="{}", server_default="{}"
    )
    parse_source: Mapped[str] = mapped_column(
        String(16), default="native", server_default="native"
    )
    ocr_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    requires_review: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false()
    )
    review_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    deleted_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    risks: Mapped[list["Risk"]] = relationship(back_populates="contract")
    clauses: Mapped[list["ContractClause"]] = relationship(
        back_populates="contract", cascade="all, delete-orphan"
    )
    parse_cache: Mapped["ContractParseCache | None"] = relationship(
        back_populates="contract", cascade="all, delete-orphan", uselist=False
    )


class ContractParseCache(Base):
    """按合同、内容哈希和解析器签名隔离的加密解析结果。"""

    __tablename__ = "contract_parse_caches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contract_id: Mapped[int] = mapped_column(
        ForeignKey("contracts.id", ondelete="CASCADE"), unique=True, index=True
    )
    content_sha256: Mapped[str] = mapped_column(String(64))
    parser_signature: Mapped[str] = mapped_column(String(64))
    payload: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    contract: Mapped["Contract"] = relationship(back_populates="parse_cache")


class ContractClause(Base):
    """一次合同审查生成的结构化条款及其原文定位锚点。"""

    __tablename__ = "contract_clauses"
    __table_args__ = (
        UniqueConstraint(
            "contract_id",
            "audit_generation",
            "chunk_id",
            name="uq_contract_clauses_generation_chunk",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contract_id: Mapped[int] = mapped_column(
        ForeignKey("contracts.id", ondelete="CASCADE"), index=True
    )
    audit_generation: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    chunk_id: Mapped[str] = mapped_column(String(64), index=True)
    clause_id: Mapped[str] = mapped_column(String(128), default="", server_default="")
    clause_path_json: Mapped[str] = mapped_column(Text, default="[]", server_default="[]")
    content: Mapped[str] = mapped_column(Text)
    block_type: Mapped[str] = mapped_column(String(32), default="clause", server_default="clause")
    char_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    char_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    parent_chunk_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    previous_chunk_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    next_chunk_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_anchors_json: Mapped[str] = mapped_column(Text, default="[]", server_default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    contract: Mapped["Contract"] = relationship(back_populates="clauses")


class AuditBatch(Base):
    """异步合同审查批次，状态和进度以数据库为准。"""
    __tablename__ = "audit_batches"
    __table_args__ = (
        UniqueConstraint("owner_id", "idempotency_key", name="uq_audit_batches_owner_idempotency"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    department: Mapped[str] = mapped_column(String(64), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128))
    request_fingerprint: Mapped[str] = mapped_column(String(64), default="", server_default="")
    dimensions_json: Mapped[str] = mapped_column(Text, default="[]")
    status: Mapped[str] = mapped_column(String(24), default="queued", index=True)
    total: Mapped[int] = mapped_column(Integer, default=0)
    completed: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    items: Mapped[list["AuditBatchItem"]] = relationship(
        back_populates="batch", cascade="all, delete-orphan"
    )


class AuditBatchItem(Base):
    """批次内单份合同的执行状态和可恢复任务元数据。"""
    __tablename__ = "audit_batch_items"
    __table_args__ = (
        UniqueConstraint("batch_id", "contract_id", name="uq_audit_batch_items_contract"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("audit_batches.id", ondelete="CASCADE"), index=True)
    contract_id: Mapped[int] = mapped_column(ForeignKey("contracts.id"), index=True)
    import_item_id: Mapped[int | None] = mapped_column(ForeignKey("import_batch_items.id"), nullable=True, index=True)
    filename: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(24), default="queued", index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    progress_stage: Mapped[str] = mapped_column(
        String(24), default="queued", server_default="queued",
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    result_json: Mapped[str] = mapped_column(Text, default="{}", server_default="{}")
    audit_generation: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    execution_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    task_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    batch: Mapped["AuditBatch"] = relationship(back_populates="items")
    contract: Mapped["Contract"] = relationship(lazy="joined")

    @property
    def requires_review(self) -> bool:
        return self.contract.requires_review

    @property
    def ocr_confidence(self) -> float | None:
        return self.contract.ocr_confidence

    @property
    def review_reason(self) -> str | None:
        return self.contract.review_reason


class ImportBatch(Base):
    """合同导入收件批次；与审查批次解耦。"""

    __tablename__ = "import_batches"
    __table_args__ = (
        UniqueConstraint("owner_id", "idempotency_key", name="uq_import_batches_owner_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128))
    request_fingerprint: Mapped[str] = mapped_column(String(64), default="")
    department: Mapped[str] = mapped_column(String(64), default="", server_default="")
    status: Mapped[str] = mapped_column(String(24), default="processing", index=True)
    total: Mapped[int] = mapped_column(Integer, default=0)
    ready: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    items: Mapped[list["ImportBatchItem"]] = relationship(
        back_populates="batch", cascade="all, delete-orphan"
    )


class ImportAppendRequest(Base):
    """导入批次追加操作的幂等记录。"""

    __tablename__ = "import_append_requests"
    __table_args__ = (
        UniqueConstraint("batch_id", "idempotency_key", name="uq_import_append_batch_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[int] = mapped_column(
        ForeignKey("import_batches.id", ondelete="CASCADE"), index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(128))
    request_fingerprint: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ImportBatchItem(Base):
    """导入批次内单份文件的持久状态。"""

    __tablename__ = "import_batch_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[int] = mapped_column(
        ForeignKey("import_batches.id", ondelete="CASCADE"), index=True
    )
    contract_id: Mapped[int | None] = mapped_column(
        ForeignKey("contracts.id"), nullable=True, index=True
    )
    filename: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    batch: Mapped["ImportBatch"] = relationship(back_populates="items")
    contract: Mapped["Contract | None"] = relationship(lazy="joined")


class AuditWindowRun(Base):
    """按任务代次、智能体和协议隔离的窗口检查点。"""

    __tablename__ = "audit_window_runs"
    __table_args__ = (
        UniqueConstraint(
            "audit_job_id", "audit_generation", "agent", "dimensions_hash",
            "window_id", "protocol_version", name="uq_audit_window_runs_identity",
        ),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contract_id: Mapped[int] = mapped_column(
        ForeignKey("contracts.id", ondelete="CASCADE"), index=True,
    )
    audit_job_id: Mapped[int] = mapped_column(Integer, index=True)
    audit_generation: Mapped[int] = mapped_column(Integer)
    agent: Mapped[str] = mapped_column(String(16))
    dimensions_hash: Mapped[str] = mapped_column(String(64))
    window_id: Mapped[str] = mapped_column(String(64))
    parent_window_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    depth: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    protocol_version: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16))
    result_json: Mapped[str] = mapped_column(Text, default="{}", server_default="{}")
    issues_json: Mapped[str] = mapped_column(Text, default="[]", server_default="[]")
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
    )


class Risk(Base):
    __tablename__ = "risks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contract_id: Mapped[int] = mapped_column(ForeignKey("contracts.id"))
    audit_job_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    level: Mapped[str] = mapped_column(String(8))  # high/medium/low
    category: Mapped[str] = mapped_column(String(64))
    agent: Mapped[str] = mapped_column(String(16), default="legal")  # 风险归属智能体：legal/finance
    original_text: Mapped[str] = mapped_column(Text)   # 原文引用
    risk_reason: Mapped[str] = mapped_column(Text, default="")  # 候选风险原因，不作为正式依据
    basis: Mapped[str] = mapped_column(Text)           # 依据来源（法规/规则，来自 RAG）
    suggestion: Mapped[str] = mapped_column(Text)      # 建议修改
    confidence: Mapped[int] = mapped_column(Integer, default=0)  # 置信度 0-100
    tier: Mapped[str] = mapped_column(String(8), default="yellow")  # 人工干预档位：green/yellow/red
    review_status: Mapped[str] = mapped_column(String(16), default="pending")  # pending/confirmed/ignored/to_modify
    rag_sources: Mapped[str] = mapped_column(Text, default="[]")   # JSON: [{content, source, score}]，RAG 检索溯源
    evidence_status: Mapped[str] = mapped_column(String(24), default="unsupported")
    original_text_verified: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    requires_manual_review: Mapped[bool] = mapped_column(Boolean, default=True)
    support_relation_status: Mapped[str] = mapped_column(String(16), default="unclear")
    support_validation_reason: Mapped[str] = mapped_column(Text, default="")
    support_validator_version: Mapped[str] = mapped_column(String(32), default="unvalidated")
    claim_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    claim_status: Mapped[str] = mapped_column(
        String(24), default="pending_evidence", server_default="pending_evidence"
    )
    source_window_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_clause_ids_json: Mapped[str] = mapped_column(Text, default="[]", server_default="[]")
    evidence_ids_json: Mapped[str] = mapped_column(Text, default="[]", server_default="[]")
    retrieval_attempts_json: Mapped[str] = mapped_column(Text, default="[]", server_default="[]")
    contract_evidence_json: Mapped[str] = mapped_column(Text, default="[]", server_default="[]")
    secondary_review_status: Mapped[str] = mapped_column(
        String(24), default="not_required", server_default="not_required",
    )
    secondary_review_reason: Mapped[str] = mapped_column(Text, default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    contract: Mapped["Contract"] = relationship(back_populates="risks")


class LegalSource(Base):
    """经核验的权威法律文件。"""

    __tablename__ = "legal_sources"
    source_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    issuing_authority: Mapped[str] = mapped_column(String(255), nullable=False)
    official_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    publication_date: Mapped[date] = mapped_column(Date, nullable=False)
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    version_status: Mapped[str] = mapped_column(String(32), nullable=False)
    retrieved_at: Mapped[date] = mapped_column(Date, nullable=False)
    file_sha256: Mapped[str] = mapped_column(String(64), nullable=False)

    articles: Mapped[list["LegalArticle"]] = relationship(
        back_populates="legal_source", cascade="all, delete-orphan"
    )


class LegalArticle(Base):
    """权威法源中的完整法条父记录。"""

    __tablename__ = "legal_articles"
    __table_args__ = (
        UniqueConstraint("source_id", "article_number", name="uq_legal_article_source_number"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("legal_sources.source_id"), index=True)
    article_number: Mapped[str] = mapped_column(String(64), nullable=False)
    article_sort: Mapped[int] = mapped_column(Integer, nullable=False)
    chapter_title: Mapped[str] = mapped_column(String(255), default="")
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    legal_source: Mapped["LegalSource"] = relationship(back_populates="articles")
    chunks: Mapped[list["KnowledgeChunk"]] = relationship(back_populates="legal_article")


class KnowledgeChunk(Base):
    """知识库切片：法规/行业规则/合同模板，供 RAG 检索。

    向量以 JSON 文本存储，SQLite/PostgreSQL 通用、可移植。
    交付期在 PostgreSQL 上可另建 pgvector 原生 Vector 列 + 距离索引优化检索性能。
    """
    __tablename__ = "knowledge_chunks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    category: Mapped[str] = mapped_column(String(32), index=True)  # law/rule/template
    source: Mapped[str] = mapped_column(String(255), default="")   # 来源（法规名/文件名）
    content: Mapped[str] = mapped_column(Text)                     # 切片正文
    embedding: Mapped[str] = mapped_column(Text, default="")       # JSON 序列化的向量
    article_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    effective_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    applicable_contract_types: Mapped[str] = mapped_column(Text, default="[]")
    applicable_dimensions: Mapped[str] = mapped_column(Text, default="[]")
    scope_mode: Mapped[str] = mapped_column(
        String(16), nullable=False, default="unclassified", server_default="unclassified"
    )
    embedding_model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    embedding_dimension: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    legal_article_id: Mapped[int | None] = mapped_column(
        ForeignKey("legal_articles.id"), nullable=True, index=True
    )
    chunk_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chunk_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chunk_schema_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    retrieval_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    embedding_signature: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    legal_article: Mapped["LegalArticle | None"] = relationship(back_populates="chunks")


class KnowledgeIndexState(Base):
    """知识库索引的单例修订号；用于使检索快照在写入后失效。"""

    __tablename__ = "knowledge_index_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class AuditLog(Base):
    """审计日志：谁在何时对什么做了什么。企业追责与合规刚需。"""
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(64))       # login/upload/audit/update_risk/export...
    target: Mapped[str] = mapped_column(String(128), default="")
    detail: Mapped[str] = mapped_column(Text, default="")
    ip: Mapped[str] = mapped_column(String(64), default="")  # 操作来源 IP（从请求真实提取，追责用）
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuditRule(Base):
    """审查规则：驱动 Agent 判定风险的业务规则，支持内置与自定义。"""
    __tablename__ = "audit_rules"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    dimension: Mapped[str] = mapped_column(String(64), default="")   # 审查维度
    level: Mapped[str] = mapped_column(String(8))                    # high/medium/low
    agent: Mapped[str] = mapped_column(String(32), default="法务 Agent")  # 法务 Agent/财务 Agent
    desc: Mapped[str] = mapped_column(Text, default="")
    builtin: Mapped[bool] = mapped_column(Integer, default=0)        # SQLite 没有 Boolean，0/1
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ContractTemplate(Base):
    """合同模板：标准条款清单，供审查时比对与参考。"""
    __tablename__ = "contract_templates"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    type: Mapped[str] = mapped_column(String(64), default="")        # 合同类型
    clauses: Mapped[str] = mapped_column(Text, default="[]")         # JSON 序列化的条款列表
    builtin: Mapped[bool] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AccessRole(Base):
    """权限矩阵：角色与模块的读写权限映射，支持在线编辑。

    perms 为 JSON 列表，与 modules 固定顺序一一对应：
    7 个模块 → ['工作台','合同审查','整改跟踪','多维报表','法规知识库','规则与模板','权限与审计']
    值 ∈ 读写/只读/无
    """
    __tablename__ = "access_roles"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(32), unique=True)     # business/legal/finance/admin
    label: Mapped[str] = mapped_column(String(32))                # 显示名称
    perms: Mapped[str] = mapped_column(Text, default="[]")        # JSON 序列化的权限列表
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LLMCallLog(Base):
    """LLM 调用记录：每次 Agent chat 调用留痕，供算力对比与可解释性审计。

    provider/model/token 用量/延迟等信息可用于：
    - OpenClaw 与通用模型的成本/延迟对比（竞赛技术分重点）
    - 审查结论可解释性溯源（哪次 LLM 调用产出了哪批风险）
    - 模型更换/降级影响分析
    """
    __tablename__ = "llm_call_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contract_id: Mapped[int | None] = mapped_column(ForeignKey("contracts.id"), nullable=True)
    audit_job_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    window_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    dimension: Mapped[str] = mapped_column(String(64), default="all", server_default="all")
    attempt: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    validation_status: Mapped[str] = mapped_column(
        String(24), default="unknown", server_default="unknown",
    )
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    agent: Mapped[str] = mapped_column(String(16), default="")       # legal/finance
    provider: Mapped[str] = mapped_column(String(32), default="")    # deepseek/qwen/openclaw
    model: Mapped[str] = mapped_column(String(64), default="")
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    finish_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    mode: Mapped[str] = mapped_column(String(8), default="llm")       # llm/mock（降级时不记录）
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LookupItem(Base):
    """可配置下拉选项：业务部门（department）/ 合同类型（contract_type）由管理员维护。

    前端合同审查页的两个下拉框从此表动态拉取，管理员可在「基础配置」Tab 增删条目。
    """
    __tablename__ = "lookup_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    category: Mapped[str] = mapped_column(String(32), index=True)   # department / contract_type
    value: Mapped[str] = mapped_column(String(128))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    contract_type_profile: Mapped["ContractTypeProfile | None"] = relationship(
        back_populates="lookup_item",
        cascade="all, delete-orphan",
        single_parent=True,
        uselist=False,
    )


class ContractTypeProfile(Base):
    """合同类型字典项的一对一分类规则。"""

    __tablename__ = "contract_type_profiles"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lookup_item_id: Mapped[int] = mapped_column(
        ForeignKey("lookup_items.id", ondelete="CASCADE"),
        unique=True,
        index=True,
    )
    aliases_json: Mapped[str] = mapped_column(Text, default="[]", server_default="[]")
    positive_signals_json: Mapped[str] = mapped_column(
        Text,
        default="[]",
        server_default="[]",
    )
    negative_signals_json: Mapped[str] = mapped_column(
        Text,
        default="[]",
        server_default="[]",
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
    lookup_item: Mapped["LookupItem"] = relationship(
        back_populates="contract_type_profile"
    )


class Rectification(Base):
    """整改项：由已确认风险生成，进入整改跟踪闭环。核心审查闭环的下游。

    字段对齐前端 stores/rectify.ts：level 用英文档位、status 用中文流转态、
    created/due 存 YYYY-MM-DD 字符串（前端直接展示，非 ISO）。
    """
    __tablename__ = "rectifications"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contract: Mapped[str] = mapped_column(String(255))   # 合同名（冗余存储，便于台账直读）
    risk: Mapped[str] = mapped_column(String(255))       # 风险描述（风险 category）
    level: Mapped[str] = mapped_column(String(8))        # high/medium/low
    owner: Mapped[str] = mapped_column(String(64), default="")   # 责任人
    status: Mapped[str] = mapped_column(String(16), default="待处理")  # 待处理/处理中/待复核/已闭环
    created: Mapped[str] = mapped_column(String(16))     # YYYY-MM-DD
    due: Mapped[str] = mapped_column(String(16))         # YYYY-MM-DD（默认创建日 +7 天）
    note: Mapped[str] = mapped_column(Text, default="")  # 备注（整改建议）
    resolution: Mapped[str] = mapped_column(Text, default="")  # 责任人提交的整改结果
    review_comment: Mapped[str] = mapped_column(Text, default="")  # 复核意见/退回原因
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    risk_id: Mapped[int | None] = mapped_column(ForeignKey("risks.id"), nullable=True)  # 溯源风险，可空
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
