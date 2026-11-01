"""Pydantic 请求/响应模型。骨架：仅示例核心结构。"""
import json
from datetime import date, datetime
from typing import Literal

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)
from app.services.audit.evidence_state import evidence_validation_mode


class RiskOut(BaseModel):
    id: int
    agent: str
    level: str
    category: str
    original_text: str
    basis: str
    suggestion: str
    confidence: int
    risk_reason: str = ""
    tier: str  # 人工干预档位：green/yellow/red
    review_status: str
    rag_sources: list[dict] = Field(default_factory=list)   # RAG 检索来源
    evidence_status: str = "unsupported"
    original_text_verified: bool | None = None
    requires_manual_review: bool = True
    support_relation_status: str = "unclear"
    support_validation_reason: str = ""
    support_validator_version: str = "unvalidated"
    support_validation_failed_stage: str = "none"
    support_validation_reason_code: str = ""
    support_validation_mode: str = "manual_only"
    applicability_status: str = "unresolved"
    applicability_reason_codes: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("applicability_reason_codes", "applicability_reason_codes_json"),
    )
    rule_executions: list[dict] = Field(
        default_factory=list,
        validation_alias=AliasChoices("rule_executions", "rule_executions_json"),
    )
    decision_trace: dict = Field(
        default_factory=dict,
        validation_alias=AliasChoices("decision_trace", "decision_trace_json"),
    )
    secondary_review_status: str = "not_required"
    secondary_review_reason: str = ""
    claim_id: str | None = None
    claim_status: str = "pending_evidence"
    source_window_id: str | None = None
    source_clause_ids: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("source_clause_ids", "source_clause_ids_json"),
    )
    evidence_ids: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("evidence_ids", "evidence_ids_json"),
    )
    retrieval_attempts: list[dict] = Field(
        default_factory=list,
        validation_alias=AliasChoices("retrieval_attempts", "retrieval_attempts_json"),
    )
    contract_evidence: list[dict] = Field(
        default_factory=list,
        validation_alias=AliasChoices("contract_evidence", "contract_evidence_json"),
    )

    model_config = {"from_attributes": True}

    @field_validator('rag_sources', mode='before')
    @classmethod
    def _parse_rag_sources(cls, v):
        """rag_sources 在 DB 里存 JSON 字符串，field_validator 读时自动反序列化。"""
        if isinstance(v, str):
            try:
                parsed = json.loads(v) if v else []
                return parsed if isinstance(parsed, list) else []
            except Exception:
                return []
        if v is None:
            return []
        return v if isinstance(v, list) else []

    @field_validator(
        "source_clause_ids",
        "evidence_ids",
        "retrieval_attempts",
        "contract_evidence",
        "applicability_reason_codes",
        "rule_executions",
        mode="before",
    )
    @classmethod
    def _parse_trace_lists(cls, value):
        if isinstance(value, str):
            try:
                parsed = json.loads(value) if value else []
            except (TypeError, ValueError):
                return []
            return parsed if isinstance(parsed, list) else []
        return value if isinstance(value, list) else []

    @field_validator("decision_trace", mode="before")
    @classmethod
    def _parse_decision_trace(cls, value):
        if isinstance(value, str):
            try:
                parsed = json.loads(value) if value else {}
            except (TypeError, ValueError):
                return {}
            return parsed if isinstance(parsed, dict) else {}
        return value if isinstance(value, dict) else {}

    @model_validator(mode="after")
    def _restore_validation_mode(self):
        self.support_validation_mode = evidence_validation_mode(self.decision_trace)
        return self


class CrossCheckOut(BaseModel):
    """交叉验证 / 冲突消解项：跨 Agent 触发的持久审查结果。"""
    id: str
    from_agent: str
    to_agent: str
    trigger: str
    action: str
    verdict: str  # conflict/watch/confirmed
    note: str
    category: str


class AuditRequest(BaseModel):
    """审查触发请求：合同类型必须由用户确认，维度为空表示全量审查。"""
    contract_type: str = ""
    dimensions: list[str] = Field(default_factory=list)


AuditStatus = Literal[
    "queued", "parsing", "reviewing", "validating",
    "done", "review_required", "audit_failed",
]


class AuditCoverageOut(BaseModel):
    planned: int = 0
    completed: int = 0


class AuditResponse(BaseModel):
    """审查触发与状态响应，以持久任务状态为事实来源。"""
    contract_id: int
    status: AuditStatus
    risk_count: int | None = None
    cross_checks: list[CrossCheckOut] = Field(default_factory=list)
    task_id: str | None = None
    batch_id: int | None = None
    job_id: int | None = None
    error_code: str | None = None
    error_message: str | None = None
    retryable: bool = False
    requires_review: bool = False
    ocr_confidence: float | None = None
    review_reason: str | None = None
    quality_reasons: list[str] = Field(default_factory=list)
    issues: list[dict] = Field(default_factory=list)
    coverage: AuditCoverageOut | None = None


class ParseResponse(BaseModel):
    contract_id: int
    status: Literal["parsed", "review_required"] = "parsed"
    elements: dict
    element_evidence: dict = Field(default_factory=dict)
    text_length: int
    total_pages: int | None = None
    missing_pages: list[int] = Field(default_factory=list)
    requires_review: bool = False
    ocr_confidence: float | None = None
    review_reason: str | None = None


class ParseErrorDetail(BaseModel):
    code: str
    detail: str
    action: str
    correlation_id: str


class ParseErrorResponse(BaseModel):
    detail: ParseErrorDetail


class ContractOut(BaseModel):
    id: int
    filename: str
    contract_type: str
    status: str
    created_at: datetime
    requires_review: bool = False
    ocr_confidence: float | None = None
    review_reason: str | None = None

    model_config = {"from_attributes": True}


class RiskStatusUpdate(BaseModel):
    review_status: str  # confirmed/ignored/to_modify
    review_comment: str = Field(default="", max_length=2000)


class KnowledgeImport(BaseModel):
    """知识库导入：一段法规/规则/模板文本，服务端切片后向量化入库。"""
    category: str = "rule"      # law/rule/template
    source: str = ""            # 来源（法规名/文件名）
    content: str                # 正文，服务端按段落切片
    article_number: str | None = None
    version: str | None = None
    effective_date: date | None = None
    expiry_date: date | None = None
    applicable_contract_types: list[str] = Field(default_factory=list)
    applicable_dimensions: list[str] = Field(default_factory=list)
    # 显式导入（legal/admin 角色）默认全局可检索；检索过滤器对 unclassified
    # 默认拒绝，若此处默认 unclassified 会导致“导入即死数据”。底层模型与
    # prepare_documents 的默认拒绝不变，作为程序化路径的安全网。
    scope_mode: str = "global"

    @field_validator("scope_mode")
    @classmethod
    def validate_scope_mode(cls, value: str) -> str:
        normalized = value.strip().casefold()
        if normalized not in {"global", "scoped", "unclassified"}:
            raise ValueError("scope_mode must be global, scoped, or unclassified")
        return normalized

    @model_validator(mode="after")
    def validate_scope_targets(self) -> "KnowledgeImport":
        if (
            self.scope_mode == "scoped"
            and not self.applicable_contract_types
            and not self.applicable_dimensions
        ):
            raise ValueError("scoped knowledge requires a contract type or audit dimension")
        return self


class AuditRuleOut(BaseModel):
    """审查规则输出：id 序列化为 R%02d 字符串，对齐前端 mock/rules.ts。"""
    id: str
    name: str
    dimension: str
    level: str      # high/medium/low
    agent: str
    desc: str
    builtin: bool

    @classmethod
    def from_orm_row(cls, row) -> "AuditRuleOut":
        return cls(
            id=f"R{row.id:02d}",
            name=row.name,
            dimension=row.dimension,
            level=row.level,
            agent=row.agent,
            desc=row.desc,
            builtin=bool(row.builtin),
        )


class AuditRuleCreate(BaseModel):
    name: str
    dimension: str = "法律条款合规性"
    level: str = "medium"
    agent: str = "法务 Agent"
    desc: str = ""


class ContractTemplateOut(BaseModel):
    """合同模板输出：clauses 从 JSON 字符串反序列化为列表。"""
    id: str
    name: str
    type: str
    clauses: list[str]
    builtin: bool

    @classmethod
    def from_orm_row(cls, row) -> "ContractTemplateOut":
        try:
            clauses = json.loads(row.clauses) if row.clauses else []
        except (json.JSONDecodeError, TypeError):
            clauses = []
        return cls(
            id=f"T{row.id:02d}",
            name=row.name,
            type=row.type,
            clauses=clauses,
            builtin=bool(row.builtin),
        )


class ContractTemplateCreate(BaseModel):
    name: str
    type: str = "软件开发外包合同"
    clauses: list[str] = Field(default_factory=list)


class RectificationEvidence(BaseModel):
    contract_id: int
    filename: str
    content_sha256: str | None = None
    description: str


class RectificationEventOut(BaseModel):
    id: int
    action: str
    actor_id: int
    actor: str
    occurred_at: datetime
    from_status: str | None = None
    to_status: str
    snapshot: dict = Field(default_factory=dict)


class RectificationOut(BaseModel):
    """整改项输出：id 序列化成前端约定的 RC001 形态字符串。"""
    id: str
    contract: str
    risk: str
    level: str          # high/medium/low
    owner: str
    status: str         # 待处理/处理中/已闭环
    created: str        # YYYY-MM-DD
    due: str            # YYYY-MM-DD
    note: str
    risk_id: int | None = None
    resolution: str = ""
    review_comment: str = ""
    submitted_at: datetime | None = None
    closed_at: datetime | None = None
    contract_id: int | None = None
    department: str = ""
    before_text: str = ""
    original_text_verified: bool | None = None
    acceptance_criteria: str = ""
    contract_stage: str = "unknown"
    handling_method: str = ""
    collaborators: list[str] = Field(default_factory=list)
    evidence: list[RectificationEvidence] = Field(default_factory=list)
    after_text: str = ""
    submitted_by: int | None = None
    reviewed_by: int | None = None
    reviewed_at: datetime | None = None
    acceptance_reason: str = ""
    residual_risk: str = ""
    accepted_at: datetime | None = None
    escalation_reason: str = ""
    escalated_at: datetime | None = None
    escalated_by: int | None = None
    version: int = 1
    events: list[RectificationEventOut] = Field(default_factory=list)
    can_manage: bool = False
    can_execute: bool = False
    can_review: bool = False
    can_accept: bool = False
    can_escalate: bool = False
    can_reopen: bool = False

    @classmethod
    def from_orm_row(cls, row) -> "RectificationOut":
        result = cls(
            id=f"RC{row.id:03d}",
            contract=row.contract,
            risk=row.risk,
            level=row.level,
            owner=row.owner,
            status=row.status,
            created=row.created,
            due=row.due,
            note=row.note or "",
            risk_id=row.risk_id,
            resolution=row.resolution or "",
            review_comment=row.review_comment or "",
            submitted_at=row.submitted_at,
            closed_at=row.closed_at,
        )
        for name in ("acceptance_criteria", "contract_stage", "handling_method", "after_text", "submitted_by", "reviewed_by", "reviewed_at", "acceptance_reason", "residual_risk", "accepted_at", "escalation_reason", "escalated_at", "escalated_by", "version"):
            value = getattr(row, name, None)
            if value is not None:
                setattr(result, name, value)
        result.collaborators = json.loads(getattr(row, "collaborators_json", "[]") or "[]")
        result.evidence = [RectificationEvidence(**item) for item in json.loads(getattr(row, "evidence_json", "[]") or "[]")]
        return result


class RectificationCreate(BaseModel):
    """先验证来源权限，再由服务校验必填计划，避免越权信息泄露。"""
    model_config = ConfigDict(extra="forbid")
    contract: str = ""
    risk: str = ""
    level: str = "medium"
    owner: str = ""
    status: str = "待处理"
    created: str | None = None
    due: str | None = None
    note: str = ""
    risk_id: int | None = None
    acceptance_criteria: str = ""
    contract_stage: str = "unknown"
    handling_method: str = ""
    collaborators: list[str] = Field(default_factory=list)


class RectificationPlanUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int | None = None
    owner: str | None = None
    due: str | None = None
    note: str | None = None
    acceptance_criteria: str | None = None
    contract_stage: str | None = None
    handling_method: str | None = None
    collaborators: list[str] | None = None


class RectificationEscalate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int | None = None
    reason: str


class LLMCallLogOut(BaseModel):
    """LLM 调用日志行：供演示「可解释性」与 OpenClaw 算力对比。"""
    id: str           # L{n:04d}
    contract_id: int | None
    audit_job_id: int | None = None
    agent: str        # legal/finance
    provider: str     # deepseek/qwen/openclaw
    model: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int
    mode: str         # llm/mock
    time: str         # YYYY-MM-DD HH:mm
    finish_reason: str | None = None


class AccessRoleOut(BaseModel):
    key: str
    label: str
    perms: list[str]  # 与 modules 等长同序，值 ∈ 读写/只读/无

    @classmethod
    def from_orm_row(cls, row) -> "AccessRoleOut":
        try:
            perms = json.loads(row.perms) if row.perms else []
        except (json.JSONDecodeError, TypeError):
            perms = []
        return cls(key=row.key, label=row.label, perms=perms)


class AccessMatrixOut(BaseModel):
    """权限矩阵响应：对象包裹（非裸数组）。"""
    modules: list[str]
    roles: list[AccessRoleOut]


class AuditLogRowOut(BaseModel):
    """审计日志行：join users 出 user/role，id 格式 L{n:04d}。"""
    id: str
    user: str
    role: str
    action: str
    target: str
    time: str   # YYYY-MM-DD HH:mm
    ip: str


class RectificationStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str  # 待处理/处理中/待复核/已闭环
    version: int | None = None
    resolution: str | None = None
    review_comment: str | None = None
    evidence_contract_ids: list[int] | None = None
    after_text: str | None = None
    acceptance_reason: str | None = None
    residual_risk: str | None = None


class HistoryRow(BaseModel):
    """审查记录行：保留原台账字段，并提供整体结论完整度。

    level/status 用中文枚举，time 为带时区的 ISO 8601 导入时间，搜索/筛选在前端本地做。
    """
    id: str            # 格式 "C{合同id:04d}"
    name: str          # 合同文件名
    type: str          # 合同类型
    submitter: str     # 上传人用户名
    time: str          # ISO 8601，含时区
    level: str         # 高风险/中风险/低风险/未发现风险/尚无法判断
    riskCount: int     # 当前任务的候选数量；完整度为 false 时不代表完整审查结论
    status: str        # 审查失败/未审查/审查中/待人工复核/未发现风险/待整改/已整改等
    assessmentComplete: bool = False
    coverage: AuditCoverageOut | None = None


class LookupItemOut(BaseModel):
    id: int
    category: str
    value: str
    sort_order: int


class LookupItemCreate(BaseModel):
    category: str   # department / contract_type
    value: str
    sort_order: int = 0


class ContractTypeProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    aliases: list[str] = Field(default_factory=list, max_length=32)
    positive_signals: list[str] = Field(default_factory=list, max_length=32)
    negative_signals: list[str] = Field(default_factory=list, max_length=32)
    enabled: bool
    version: int = Field(ge=1)


class ContractTypeProfileOut(ContractTypeProfileUpdate):
    lookup_item_id: int
    value: str


class DepartmentScopeUserOut(BaseModel):
    id: int
    username: str
    role: str
    department: str
    authorized_departments: list[str]


class DepartmentScopeUpdate(BaseModel):
    departments: list[str] = Field(default_factory=list, max_length=100)
