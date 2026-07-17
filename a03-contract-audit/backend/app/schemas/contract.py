"""Pydantic 请求/响应模型。骨架：仅示例核心结构。"""
import json
from datetime import datetime

from pydantic import BaseModel, field_validator, model_validator


class RiskOut(BaseModel):
    id: int
    agent: str
    level: str
    category: str
    original_text: str
    basis: str
    suggestion: str
    confidence: int
    tier: str  # 人工干预档位：green/yellow/red
    review_status: str
    rag_sources: list[dict] = []   # RAG 检索来源：[{content, source, score}]

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


class CrossCheckOut(BaseModel):
    """交叉验证 / 冲突消解项：跨 Agent 触发的复查结果（审查态动态结果，不落库）。"""
    id: str
    from_agent: str
    to_agent: str
    trigger: str
    action: str
    verdict: str  # conflict/watch/confirmed
    note: str
    category: str


class AuditRequest(BaseModel):
    """审查触发请求：可选维度列表，空/不传表示全量审查。"""
    dimensions: list[str] = []


class AuditResponse(BaseModel):
    """审查触发响应：同步返回风险数与冲突项；异步返回 task_id。"""
    contract_id: int
    status: str
    risk_count: int | None = None
    cross_checks: list[CrossCheckOut] = []
    task_id: str | None = None


class ContractOut(BaseModel):
    id: int
    filename: str
    contract_type: str
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class RiskStatusUpdate(BaseModel):
    review_status: str  # confirmed/ignored/to_modify


class KnowledgeImport(BaseModel):
    """知识库导入：一段法规/规则/模板文本，服务端切片后向量化入库。"""
    category: str = "rule"      # law/rule/template
    source: str = ""            # 来源（法规名/文件名）
    content: str                # 正文，服务端按段落切片


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
    clauses: list[str] = []


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

    @classmethod
    def from_orm_row(cls, row) -> "RectificationOut":
        return cls(
            id=f"RC{row.id:03d}",
            contract=row.contract,
            risk=row.risk,
            level=row.level,
            owner=row.owner,
            status=row.status,
            created=row.created,
            due=row.due,
            note=row.note or "",
        )


class RectificationCreate(BaseModel):
    """新建整改项：AuditView 复核确认风险时生成。due 省略则默认创建日 +7 天。"""
    contract: str
    risk: str
    level: str = "medium"
    owner: str = ""
    status: str = "待处理"
    created: str | None = None
    due: str | None = None
    note: str = ""
    risk_id: int | None = None


class LLMCallLogOut(BaseModel):
    """LLM 调用日志行：供演示「可解释性」与 OpenClaw 算力对比。"""
    id: str           # L{n:04d}
    contract_id: int | None
    agent: str        # legal/finance
    provider: str     # deepseek/qwen/openclaw
    model: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int
    mode: str         # llm/mock
    time: str         # YYYY-MM-DD HH:mm


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
    status: str  # 待处理/处理中/已闭环


class HistoryRow(BaseModel):
    """审查记录行：前端 HistoryView 台账展示。8 字段，与前端 mock/history.ts 精确对齐。

    level/status 用中文枚举，time 格式 YYYY-MM-DD HH:mm，搜索/筛选在前端本地做。
    """
    id: str            # 格式 "C{合同id:04d}"
    name: str          # 合同文件名
    type: str          # 合同类型
    submitter: str     # 上传人用户名
    time: str          # YYYY-MM-DD HH:mm
    level: str         # 高风险/中风险/低风险
    riskCount: int
    status: str        # 合规/待整改/已整改


class LookupItemOut(BaseModel):
    id: int
    category: str
    value: str
    sort_order: int


class LookupItemCreate(BaseModel):
    category: str   # department / contract_type
    value: str
    sort_order: int = 0
