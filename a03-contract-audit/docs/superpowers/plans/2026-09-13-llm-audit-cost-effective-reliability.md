# 大模型合同审查精确可靠与成本控制 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将当前可能把模型截断结果标记为成功的审查链路，改造成可恢复、可验证、选择性复核且能够用证据比较质量与成本的可靠审查流程。

**Architecture:** 保留现有条款结构化、双 Agent、RAG、generation 和任务租约，在其上增加结构化响应协议、自适应窗口执行器、窗口级持久检查点和统一质量门禁。正常窗口只调用主审模型；截断时仅拆分失败窗口，高风险或冲突项才进入二次复核。

**Tech Stack:** Python 3、FastAPI、Pydantic v2、SQLAlchemy、Alembic、Celery、pytest、Vue 3、TypeScript、Pinia、Element Plus、Playwright。

**Design:** `docs/superpowers/specs/2026-09-13-llm-audit-cost-effective-reliability-design.md`

---

## 文件职责

| 文件 | 职责 |
|---|---|
| `backend/app/llm/base.py` | 定义带错误码的 LLM 异常、响应和可选调用参数 |
| `backend/app/llm/adapters/openai_compatible.py` | 将单次 token 预算、JSON 模式和调用标识映射到兼容协议 |
| `backend/app/services/audit/protocol.py` | 定义候选风险和复核决定的严格 Pydantic 协议 |
| `backend/app/services/audit/review_pipeline.py` | 执行分页、格式重试、截断拆分和窗口结果恢复 |
| `backend/app/services/audit/window_repository.py` | 以独立短事务保存、读取窗口检查点和调用观测 |
| `backend/app/services/audit/result_quality.py` | 根据覆盖率、截断、证据和复核结果计算终态 |
| `backend/app/services/audit/secondary_review.py` | 只复核高风险、冲突或可判定的证据不足项 |
| `backend/app/services/audit/auditor.py` | 保留 Agent 编排、共享上下文、RAG 绑定和风险合并 |
| `backend/app/services/audit/runner.py` | 原子发布正式风险和最终质量状态 |
| `backend/app/models/models.py` | `AuditWindowRun`、LLM 观测字段和二次复核字段 |
| `backend/evaluation/audit_quality.py` | 计算审查精确率、召回率、截断率和错误成功率 |
| `backend/evaluation/audit_comparison.py` | 在通过质量门槛的候选中比较 tokens 与 P95 |
| `frontend/src/views/AuditView.vue` | 展示审查、校验、需人工复核和失败状态 |

生产代码不保留“旧流程”开关。旧流程基线在改动前记录，避免为了 A/B 测试长期保留已知错误路径。

### Task 1: 扩展 LLM 协议且保持现有调用兼容

**Files:**
- Modify: `backend/app/llm/base.py:11-33`
- Modify: `backend/app/llm/adapters/openai_compatible.py:20-119`
- Modify: `backend/app/llm/adapters/local_embedding.py:49-50`
- Test: `backend/tests/test_llm_adapter.py`

- [ ] **Step 1: 写失败测试，锁定单次调用选项和结构化错误**

在 `backend/tests/test_llm_adapter.py` 增加：

```python
from app.llm.base import ChatOptions, LLMError


def test_chat_options_override_budget_and_enable_json_object(monkeypatch):
    captured: dict = {}

    def fake_post(_url, *, json, headers, timeout):
        captured.update({"json": json, "headers": headers, "timeout": timeout})
        return _Response()

    monkeypatch.setattr("app.llm.adapters.openai_compatible.httpx.post", fake_post)
    adapter = OpenAICompatibleAdapter(
        base_url="https://llm.example/v1",
        max_output_tokens=1600,
    )

    adapter.chat(
        "system",
        "user",
        options=ChatOptions(
            max_output_tokens=2400,
            response_format={"type": "json_object"},
            request_id="audit-7-window-a-attempt-1",
        ),
    )

    assert captured["json"]["max_tokens"] == 2400
    assert captured["json"]["response_format"] == {"type": "json_object"}
    assert captured["headers"]["X-Request-ID"] == "audit-7-window-a-attempt-1"


def test_timeout_exposes_safe_typed_error(monkeypatch):
    request = httpx.Request("POST", "https://llm.example/v1/chat/completions")
    monkeypatch.setattr(
        "app.llm.adapters.openai_compatible.httpx.post",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(httpx.ReadTimeout("secret", request=request)),
    )

    with pytest.raises(LLMError) as exc_info:
        OpenAICompatibleAdapter(base_url="https://llm.example/v1").chat("system", "user")

    assert exc_info.value.code == "MODEL_TIMEOUT"
    assert exc_info.value.retryable is True
    assert "secret" not in str(exc_info.value)
```

- [ ] **Step 2: 运行测试并确认失败原因正确**

Run:

```powershell
Set-Location backend
.\.venv\Scripts\python.exe -m pytest tests\test_llm_adapter.py -q
```

Expected: FAIL，缺少 `ChatOptions`，且 `LLMError` 没有 `code/retryable`。

- [ ] **Step 3: 增加兼容式协议类型**

在 `backend/app/llm/base.py` 增加并更新抽象方法：

```python
from dataclasses import dataclass


class LLMError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        code: str = "MODEL_UNAVAILABLE",
        retryable: bool = True,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True)
class ChatOptions:
    max_output_tokens: int | None = None
    response_format: dict[str, str] | None = None
    request_id: str | None = None


class LLMAdapter(ABC):
    @abstractmethod
    def chat(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.2,
        options: ChatOptions | None = None,
    ) -> LLMResponse:
        """单轮对话；options 为空时保持原有调用行为。"""
```

同步给 `LocalEmbeddingAdapter.chat` 增加可选 `options` 参数，但仍抛出原有“不支持 chat”异常。

- [ ] **Step 4: 在 OpenAI 兼容适配器中映射选项**

将请求构造调整为：

```python
def chat(
    self,
    system: str,
    user: str,
    *,
    temperature: float = 0.2,
    options: ChatOptions | None = None,
) -> LLMResponse:
    options = options or ChatOptions()
    max_tokens = options.max_output_tokens or self.max_output_tokens
    if max_tokens <= 0:
        raise ValueError("max_output_tokens 必须大于 0")
    payload = {
        "model": self.model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    if options.response_format is not None:
        payload["response_format"] = options.response_format
    data, latency_ms = self._post(
        "/chat/completions",
        payload,
        request_id=options.request_id,
    )
    return self._response_from_data(data, latency_ms)
```

让 `_post` 接收 `request_id`，只将非空值写入 `X-Request-ID`。将超时、HTTP 状态和网络错误分别映射为 `MODEL_TIMEOUT`、`MODEL_REJECTED`、`MODEL_UNAVAILABLE`，日志继续禁止记录响应正文和底层异常文本。

- [ ] **Step 5: 运行适配器和全部调用者测试**

Run:

```powershell
Set-Location backend
.\.venv\Scripts\python.exe -m pytest tests\test_llm_adapter.py tests\test_parser_contracts.py tests\test_contract_quality_api.py tests\test_audit_evidence.py -q
```

Expected: PASS；风险问答和要素抽取的旧调用不需要传 `ChatOptions`。

- [ ] **Step 6: 提交协议扩展**

```powershell
git add backend/app/llm/base.py backend/app/llm/adapters/openai_compatible.py backend/app/llm/adapters/local_embedding.py backend/tests/test_llm_adapter.py
git commit -m "feat: add typed llm call options"
```

### Task 2: 建立严格候选风险协议

**Files:**
- Create: `backend/app/services/audit/protocol.py`
- Create: `backend/tests/test_audit_protocol.py`

- [ ] **Step 1: 写失败测试，拒绝顶层数组、超量风险和过长字段**

```python
import json
import pytest
from pydantic import ValidationError

from app.services.audit.protocol import parse_risk_envelope


def _risk(index: int) -> dict:
    return {
        "level": "high",
        "category": f"付款风险{index}",
        "quote": "验收前支付全部价款",
        "reason": "付款节点早于验收，缺少履约保障。",
        "suggestion": "改为验收后分期支付并设置质保金。",
    }


def test_risk_envelope_accepts_at_most_five_compact_risks():
    parsed = parse_risk_envelope(json.dumps({"risks": [_risk(1)], "has_more": False}))
    assert parsed.risks[0].category == "付款风险1"

    with pytest.raises(ValidationError):
        parse_risk_envelope(json.dumps({"risks": [_risk(i) for i in range(6)], "has_more": False}))


@pytest.mark.parametrize("payload", ["[]", "```json\n{}\n```", '{"risks": [], "extra": 1}'])
def test_risk_envelope_fails_closed_for_non_protocol_output(payload: str):
    with pytest.raises((ValidationError, ValueError)):
        parse_risk_envelope(payload)
```

- [ ] **Step 2: 运行测试并确认协议模块不存在**

Run: `backend\.venv\Scripts\python.exe -m pytest backend\tests\test_audit_protocol.py -q`

Expected: FAIL with `ModuleNotFoundError: app.services.audit.protocol`。

- [ ] **Step 3: 实现严格 Pydantic 协议**

```python
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


AUDIT_PROTOCOL_VERSION = "candidate-v1"
AUDIT_JSON_FORMAT = {"type": "json_object"}


class RiskCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    level: Literal["high", "medium", "low"]
    category: str = Field(min_length=2, max_length=64)
    quote: str = Field(min_length=2, max_length=500)
    reason: str = Field(min_length=4, max_length=800)
    suggestion: str = Field(min_length=4, max_length=800)


class RiskEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    risks: list[RiskCandidate] = Field(default_factory=list, max_length=5)
    has_more: bool = False


def parse_risk_envelope(text: str) -> RiskEnvelope:
    stripped = text.strip()
    if not stripped.startswith("{") or not stripped.endswith("}"):
        raise ValueError("模型输出不是严格 JSON 对象")
    return RiskEnvelope.model_validate_json(stripped)
```

同文件增加以下协议；字段全部 `extra="forbid"`：

```python
ReviewIssueCode = Literal[
    "OUTPUT_TRUNCATED",
    "INVALID_MODEL_OUTPUT",
    "MODEL_TIMEOUT",
    "MODEL_UNAVAILABLE",
    "PAGINATION_EXHAUSTED",
    "EVIDENCE_UNRESOLVED",
    "ORIGINAL_TEXT_UNRESOLVED",
    "PARSE_QUALITY_LOW",
    "CONTRACT_TEXT_INCOMPLETE",
    "SECONDARY_REVIEW_CONFLICT",
]


class ReviewIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: ReviewIssueCode
    agent: str = Field(min_length=1, max_length=16)
    window_id: str | None = Field(default=None, max_length=64)
    detail: str = Field(min_length=1, max_length=255)


class AgentReviewResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidates: list[RiskCandidate] = Field(default_factory=list)
    issues: list[ReviewIssue] = Field(default_factory=list)
    complete: bool
    planned_windows: int = Field(default=1, ge=1)
    completed_windows: int = Field(default=0, ge=0)
```

同时定义 `SecondaryDecision` 和 `SecondaryEnvelope`；Task 7 再补齐其最终字段。`AgentReviewResult` 使用 Pydantic 而非 dataclass，确保检查点可以通过 `model_dump_json()/model_validate_json()` 无损恢复。

- [ ] **Step 4: 运行协议测试**

Run: `backend\.venv\Scripts\python.exe -m pytest backend\tests\test_audit_protocol.py -q`

Expected: PASS。

- [ ] **Step 5: 提交协议模型**

```powershell
git add backend/app/services/audit/protocol.py backend/tests/test_audit_protocol.py
git commit -m "feat: define strict audit response protocol"
```

### Task 3: 实现自适应窗口执行器

**Files:**
- Create: `backend/app/services/audit/review_pipeline.py`
- Create: `backend/tests/test_review_pipeline.py`
- Modify: `backend/app/services/rag/contract_structure.py:87-117`
- Test: `backend/tests/test_contract_structure.py`

- [ ] **Step 1: 写失败测试，证明只拆分截断窗口**

测试使用队列式假 Adapter：父窗口返回 `finish_reason="length"`，两个子窗口返回合法 JSON。断言：

```python
def test_truncated_window_is_split_without_replaying_successful_siblings():
    adapter = QueueAdapter([
        LLMResponse(text="{}", model="test", finish_reason="length"),
        valid_response("第一条"),
        valid_response("第二条"),
    ])
    reviewer = WindowReviewer(adapter, sleep=lambda _seconds: None)

    result = reviewer.review(request_for("第一条 风险。\n第二条 风险。"))

    assert result.complete is True
    assert len(result.candidates) == 2
    assert [call.window.depth for call in adapter.calls] == [0, 1, 1]
    assert all(issue.code != "OUTPUT_TRUNCATED" for issue in result.issues)
```

再增加四个测试：合法响应只调用一次、非法 JSON 只重试一次、`has_more` 最多三页且去重、连续模型错误产生结构化 issue 且不生成假风险。

- [ ] **Step 2: 运行执行器测试并确认失败**

Run:

```powershell
Set-Location backend
.\.venv\Scripts\python.exe -m pytest tests\test_review_pipeline.py tests\test_contract_structure.py -q
```

Expected: FAIL，缺少 `WindowReviewer` 和窗口拆分函数。

- [ ] **Step 3: 增加稳定的窗口拆分函数**

在 `contract_structure.py` 增加：

```python
def split_contract_window(window: ContractWindow) -> list[ContractWindow]:
    target = max(200, len(window.text) // 2)
    children = build_contract_windows(window.text, max_chars=target)
    if len(children) < 2 and len(window.text) > 200:
        children = build_contract_windows(window.text, max_chars=max(200, target // 2))
    return children if len(children) >= 2 else []
```

测试必须断言子窗口拼接后覆盖父窗口全部非空文本、条款 ID 不丢失、相同输入生成相同 `window_id`。

- [ ] **Step 4: 实现窗口执行器的公开接口**

`review_pipeline.py` 定义：

```python
@dataclass(frozen=True)
class ReviewWindow:
    window: ContractWindow
    parent_window_id: str | None = None
    depth: int = 0


@dataclass(frozen=True)
class WindowReviewRequest:
    contract_id: int | None
    audit_job_id: int | None
    audit_generation: int
    agent: str
    dimensions: tuple[str, ...]
    review_window: ReviewWindow
    system_prompt: str
    build_user_prompt: Callable[[ReviewWindow, int, tuple[str, ...]], str]


class WindowCheckpoint(Protocol):
    def load_valid(self, request: WindowReviewRequest) -> AgentReviewResult | None: ...
    def save_valid(self, request: WindowReviewRequest, result: AgentReviewResult) -> None: ...
    def record_call(
        self,
        request: WindowReviewRequest,
        *,
        page: int,
        attempt: int,
        response: LLMResponse | None,
        validation_status: str,
        error_code: str | None,
    ) -> None: ...


class WindowReviewer:
    def __init__(
        self,
        adapter: LLMAdapter,
        *,
        checkpoint: WindowCheckpoint | None = None,
        max_split_depth: int = 2,
        max_pages: int = 3,
        max_call_attempts: int = 3,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.adapter = adapter
        self.checkpoint = checkpoint or NullWindowCheckpoint()
        self.max_split_depth = max_split_depth
        self.max_pages = max_pages
        self.max_call_attempts = max_call_attempts
        self.sleep = sleep

    def review(self, request: WindowReviewRequest) -> AgentReviewResult:
        cached = self.checkpoint.load_valid(request)
        if cached is not None:
            return cached
        return self._review_uncached(request)
```

`_review_uncached` 必须按以下固定顺序执行：合法分页结果 → 保存检查点；`length` → 仅拆分本窗口；非法 JSON → 同窗口格式重试一次；可重试 LLMError → `0/1/2` 秒退避；达到上限 → 返回 issue。分页去重键使用 `sha256(agent + category + quote)`，不得依赖模型生成 ID。

- [ ] **Step 5: 运行执行器与结构测试**

Run: `backend\.venv\Scripts\python.exe -m pytest backend\tests\test_review_pipeline.py backend\tests\test_contract_structure.py -q`

Expected: PASS，且测试使用假 Adapter，不调用公网模型。

- [ ] **Step 6: 提交自适应执行器**

```powershell
git add backend/app/services/audit/review_pipeline.py backend/app/services/rag/contract_structure.py backend/tests/test_review_pipeline.py backend/tests/test_contract_structure.py
git commit -m "feat: add adaptive audit window recovery"
```

### Task 4: 持久化窗口检查点与调用观测

**Files:**
- Modify: `backend/app/models/models.py:239-275,417-437`
- Create: `backend/app/services/audit/window_repository.py`
- Create: `backend/alembic/versions/20260913_02_audit_window_reliability.py`
- Modify: `backend/app/db/init_db.py:22-153`
- Create: `backend/tests/test_audit_window_repository.py`
- Modify: `backend/tests/test_merge_readiness_unittest.py:124-221`

- [ ] **Step 1: 写失败测试，锁定检查点身份、恢复行为和日志字段**

在 `backend/tests/test_audit_window_repository.py` 增加：

```python
from sqlalchemy.orm import sessionmaker

from app.models.models import AuditWindowRun, LLMCallLog
from app.services.audit.protocol import AgentReviewResult
from app.services.audit.window_repository import SqlAlchemyWindowCheckpoint


def test_window_identity_contains_generation_agent_dimensions_and_protocol(db, request_for):
    factory = sessionmaker(bind=db.get_bind(), expire_on_commit=False)
    repository = SqlAlchemyWindowCheckpoint(factory)
    request = request_for(
        contract_id=7,
        audit_job_id=11,
        audit_generation=3,
        agent="legal",
        dimensions=("breach", "payment"),
        window_id="window-a",
    )
    result = AgentReviewResult(candidates=[], issues=[], complete=True)

    repository.save_valid(request, result)
    repository.save_valid(request, result)

    rows = db.query(AuditWindowRun).all()
    assert len(rows) == 1
    assert rows[0].dimensions_hash == repository.dimensions_hash(request.dimensions)
    assert repository.load_valid(request) == result


def test_call_log_records_failure_without_prompt_or_response(db, request_for):
    factory = sessionmaker(bind=db.get_bind(), expire_on_commit=False)
    repository = SqlAlchemyWindowCheckpoint(factory)
    repository.record_call(
        request_for(contract_id=7, audit_job_id=11, window_id="window-a"),
        page=1,
        attempt=2,
        response=None,
        validation_status="failed",
        error_code="MODEL_TIMEOUT",
    )

    row = db.query(LLMCallLog).one()
    assert (row.window_id, row.dimension, row.attempt) == ("window-a", "all", 2)
    assert (row.validation_status, row.error_code) == ("failed", "MODEL_TIMEOUT")
    assert not hasattr(row, "prompt_text")
    assert not hasattr(row, "response_text")
```

再增加一个事务隔离测试：`record_call()` 提交失败时只记录安全日志，不回滚调用方正在进行的审查事务；`save_valid()` 使用独立会话提交后，新的 repository 实例仍能恢复结果。

- [ ] **Step 2: 运行测试并确认模型与 repository 尚不存在**

Run:

```powershell
Set-Location backend
.\.venv\Scripts\python.exe -m pytest tests\test_audit_window_repository.py -q
```

Expected: FAIL，缺少 `AuditWindowRun` 和 `window_repository`。

- [ ] **Step 3: 增加最小持久化模型**

在 `models.py` 增加：

```python
class AuditWindowRun(Base):
    __tablename__ = "audit_window_runs"
    __table_args__ = (
        UniqueConstraint(
            "audit_job_id",
            "audit_generation",
            "agent",
            "dimensions_hash",
            "window_id",
            "protocol_version",
            name="uq_audit_window_runs_identity",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contract_id: Mapped[int] = mapped_column(
        ForeignKey("contracts.id", ondelete="CASCADE"), index=True
    )
    audit_job_id: Mapped[int] = mapped_column(Integer, index=True)
    audit_generation: Mapped[int] = mapped_column(Integer)
    agent: Mapped[str] = mapped_column(String(16))
    dimensions_hash: Mapped[str] = mapped_column(String(64))
    window_id: Mapped[str] = mapped_column(String(64))
    parent_window_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    depth: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    protocol_version: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16))  # valid/failed
    result_json: Mapped[str] = mapped_column(Text, default="{}", server_default="{}")
    issues_json: Mapped[str] = mapped_column(Text, default="[]", server_default="[]")
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
```

`audit_job_id` 对应持久批次项 ID，不设外键，保持与 `Risk.audit_job_id`、同步测试和数据迁移的现有口径一致。同步端点仍使用 `NullWindowCheckpoint`；只有具有非空持久任务 ID 的异步运行启用跨进程恢复。

给 `LLMCallLog` 增加 `window_id: String(64)`、`dimension: String(64)`、`attempt: Integer`、`validation_status: String(24)` 和 `error_code: String(64) nullable`。给 `Risk` 增加 `secondary_review_status: String(24)` 与 `secondary_review_reason: Text`，默认分别为 `not_required` 和空字符串。

- [ ] **Step 4: 实现独立短事务 repository**

`window_repository.py` 的核心接口为：

```python
class SqlAlchemyWindowCheckpoint(WindowCheckpoint):
    def __init__(self, session_factory=SessionLocal) -> None:
        self.session_factory = session_factory

    @staticmethod
    def dimensions_hash(dimensions: tuple[str, ...]) -> str:
        canonical = json.dumps(sorted(set(dimensions)), ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def load_valid(self, request: WindowReviewRequest) -> AgentReviewResult | None:
        if request.audit_job_id is None:
            return None
        with self.session_factory() as db:
            row = self._identity_query(db, request).filter(
                AuditWindowRun.status == "valid"
            ).one_or_none()
            return AgentReviewResult.model_validate_json(row.result_json) if row else None

    def save_valid(self, request: WindowReviewRequest, result: AgentReviewResult) -> None:
        if request.audit_job_id is None:
            return
        with self.session_factory() as db, db.begin():
            row = self._identity_query(db, request).with_for_update().one_or_none()
            if row is None:
                row = AuditWindowRun(**self._identity_values(request))
                db.add(row)
            row.status = "valid"
            row.result_json = result.model_dump_json()
            row.issues_json = json.dumps(
                [issue.model_dump(mode="json") for issue in result.issues],
                ensure_ascii=False,
            )
```

`record_call()` 每次自行创建并关闭 Session；成功响应记录 tokens、模型、`finish_reason`，异常调用将 tokens 记为 0 并写结构化 `error_code`。任何日志写入失败只输出 `exception_type`，不得记录 prompt、响应正文、密钥或底层异常文本。并发插入同一检查点命中唯一约束时捕获 `IntegrityError`、回滚并重新读取；不得产生重复记录，也不得用“先查后插”假设替代唯一约束。

- [ ] **Step 5: 增加 Alembic 与 SQLite 开发迁移**

创建 revision `20260913_02`，`down_revision = "20260913_01"`。`upgrade()` 创建 `audit_window_runs`、唯一约束和两个索引，并增量添加上述 7 个字段；`downgrade()` 以严格反序删除索引、字段和表。

同步扩展 `init_db.py` 的 `_DEV_COLUMNS` 与 `_DEV_INDEXES`，只做 SQLite 开发库的缺列补齐，不在应用启动时重建表或删除数据。迁移部署前要求停止旧 worker；迁移中将遗留的 `contracts.status='auditing'` 和 `audit_batch_items.status='auditing'` 更新为 `reviewing`，避免新状态机无法恢复旧任务。

- [ ] **Step 6: 验证 repository、开发迁移和 Alembic 正反迁移**

Run:

```powershell
Set-Location backend
.\.venv\Scripts\python.exe -m pytest tests\test_audit_window_repository.py tests\test_merge_readiness_unittest.py tests\test_rag_evidence_persistence.py -q
$env:SQLITE_PATH='../outputs/audit-window-migration.db'
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m alembic downgrade 20260913_01
.\.venv\Scripts\python.exe -m alembic upgrade head
Remove-Item Env:SQLITE_PATH
```

Expected: pytest PASS；三条 Alembic 命令退出码均为 0；`head` 为 `20260913_02`。迁移数据库位于已忽略的仓库根目录 `outputs/`，不提交。

- [ ] **Step 7: 提交检查点持久化**

```powershell
git add backend/app/models/models.py backend/app/services/audit/window_repository.py backend/app/db/init_db.py backend/alembic/versions/20260913_02_audit_window_reliability.py backend/tests/test_audit_window_repository.py backend/tests/test_merge_readiness_unittest.py
git commit -m "feat: persist audit window checkpoints"
```

### Task 5: 接入审查器并建立统一质量门禁

**Files:**
- Modify: `backend/app/services/audit/auditor.py:1-405`
- Create: `backend/app/services/audit/result_quality.py`
- Create: `backend/tests/test_audit_result_quality.py`
- Modify: `backend/tests/test_audit_evidence.py:45-181`
- Modify: `backend/tests/test_audit_runner_quality.py:388-430`
- Modify: `backend/tests/test_rag_grounding.py:40-52`
- Modify: `backend/tests/test_contract_logic.py:50-65`

- [ ] **Step 1: 写失败测试，禁止假风险并锁定终态门槛**

在 `test_audit_result_quality.py` 增加：

```python
from app.services.audit.result_quality import AuditCoverage, decide_audit_status


def test_truncated_window_can_never_be_done():
    decision = decide_audit_status(
        risks=[supported_risk()],
        issues=[issue("OUTPUT_TRUNCATED", window_id="w-2")],
        coverage=AuditCoverage(planned=4, completed=3),
    )
    assert decision.status == "review_required"
    assert decision.requires_review is True


def test_no_usable_result_is_audit_failed():
    decision = decide_audit_status(
        risks=[],
        issues=[issue("MODEL_UNAVAILABLE", window_id="w-1")],
        coverage=AuditCoverage(planned=2, completed=0),
    )
    assert decision.status == "audit_failed"


def test_done_requires_complete_coverage_verified_quotes_and_evidence():
    decision = decide_audit_status(
        risks=[supported_risk(original_text_verified=True)],
        issues=[],
        coverage=AuditCoverage(planned=2, completed=2),
    )
    assert decision.status == "done"
```

在 `test_audit_evidence.py` 将旧的降级断言替换为：当一个窗口连续返回非法 JSON 时，结果的 `issues` 包含 `INVALID_MODEL_OUTPUT`，`risks` 中不存在 `category == "审查引擎降级"`，完整覆盖率为假。

- [ ] **Step 2: 运行质量与审查器测试并确认失败**

Run:

```powershell
Set-Location backend
.\.venv\Scripts\python.exe -m pytest tests\test_audit_result_quality.py tests\test_audit_evidence.py tests\test_rag_grounding.py tests\test_contract_logic.py -q
```

Expected: FAIL，缺少 `result_quality`，且现有 `audit_contract()` 仍生成“审查引擎降级”风险。

- [ ] **Step 3: 定义单一质量判定函数**

`result_quality.py` 定义：

```python
AuditTerminalStatus = Literal["done", "review_required", "audit_failed"]


@dataclass(frozen=True)
class AuditCoverage:
    planned: int
    completed: int

    @property
    def complete(self) -> bool:
        return self.planned > 0 and self.completed == self.planned


@dataclass(frozen=True)
class AuditQualityDecision:
    status: AuditTerminalStatus
    requires_review: bool
    reasons: tuple[str, ...]


def decide_audit_status(
    *,
    risks: Sequence[Mapping[str, object]],
    issues: Sequence[ReviewIssue],
    coverage: AuditCoverage,
) -> AuditQualityDecision:
    usable = [risk for risk in risks if risk.get("original_text_verified") is True]
    if not usable and coverage.completed == 0:
        return AuditQualityDecision("audit_failed", False, _reason_codes(issues, coverage))
    evidence_pending = any(
        risk.get("evidence_status") != "supported"
        or risk.get("support_relation_status") != "supported"
        for risk in risks
    )
    quote_pending = any(
        risk.get("original_text_verified") is not True
        for risk in risks
    )
    secondary_pending = any(
        risk.get("secondary_review_status") in {"pending", "conflict", "manual_required"}
        for risk in risks
    )
    if (
        not coverage.complete
        or issues
        or quote_pending
        or evidence_pending
        or secondary_pending
    ):
        return AuditQualityDecision("review_required", True, _reason_codes(issues, coverage, risks))
    return AuditQualityDecision("done", False, ())
```

`_reason_codes()` 返回稳定、去重的机器码；面向用户的中文说明在 API 层映射，避免用自由文本驱动状态机。无风险但所有计划窗口均成功完成可以是 `done`；“无可用结果且所有窗口失败”才是 `audit_failed`。

- [ ] **Step 4: 用 WindowReviewer 替换直接窗口循环**

保留 `_AGENT_ORDER`、维度路由、共享上下文、确定性付款检查、RAG 绑定与 `detect_conflicts()`。将 `_agent_audit()` 的 `adapter.chat()`/JSON 数组解析循环替换为：

```python
reviewer = WindowReviewer(
    get_llm_adapter(),
    checkpoint=(
        SqlAlchemyWindowCheckpoint()
        if audit_job_id is not None
        else NullWindowCheckpoint()
    ),
)
agent_result = reviewer.review(
    WindowReviewRequest(
        contract_id=contract_id,
        audit_job_id=audit_job_id,
        audit_generation=audit_generation,
        agent=role,
        dimensions=tuple(selected_dimensions),
        review_window=ReviewWindow(window),
        system_prompt=system_prompt,
        build_user_prompt=build_user_prompt,
    )
)
```

候选项通过 `_normalize_candidate()` 转成现有风险字段，再执行原文定位和 `_ground_risks()`。原文定位必须是对当前窗口或完整合同的精确子串匹配；`（全文未检出）` 不得标记为已验证。每个 Agent 返回 `risks/issues/planned_windows/completed_windows`，`audit_contract()` 聚合为：

```python
return {
    "risks": all_risks,
    "cross_checks": cross_checks,
    "issues": all_issues,
    "coverage": {"planned": planned, "completed": completed},
    "timings": timings,
}
```

删除 `except ValueError` 下生成“审查引擎降级”风险的分支；协议、截断和局部模型失败只能形成 `ReviewIssue`。保留 `LLMError` 的任务级处理，但仅在没有窗口级恢复空间时向上抛出。

- [ ] **Step 5: 运行审查器、质量门禁与现有 RAG 回归测试**

Run:

```powershell
Set-Location backend
.\.venv\Scripts\python.exe -m pytest tests\test_audit_result_quality.py tests\test_audit_evidence.py tests\test_audit_runner_quality.py tests\test_rag_grounding.py tests\test_contract_logic.py tests\test_evidence_support_validation.py -q
```

Expected: PASS；测试中不存在公网调用；代码搜索不再命中正式风险类别“审查引擎降级”。

- [ ] **Step 6: 提交审查器集成**

```powershell
git add backend/app/services/audit/auditor.py backend/app/services/audit/result_quality.py backend/tests/test_audit_result_quality.py backend/tests/test_audit_evidence.py backend/tests/test_audit_runner_quality.py backend/tests/test_rag_grounding.py backend/tests/test_contract_logic.py
git commit -m "feat: enforce reliable audit result quality"
```

### Task 6: 对齐 Runner、任务状态与 API 语义

**Files:**
- Modify: `backend/app/services/audit/runner.py:42-207,229-315`
- Modify: `backend/app/tasks/audit_tasks.py:20-196`
- Modify: `backend/app/services/batch/service.py:1-62`
- Modify: `backend/app/schemas/batch.py:1-39`
- Modify: `backend/app/schemas/contract.py:1-44,99-113`
- Modify: `backend/app/api/v1/endpoints/contracts.py:463-538`
- Modify: `backend/app/api/v1/endpoints/batches.py:64-78`
- Modify: `backend/tests/test_batch_service.py`
- Modify: `backend/tests/test_audit_job_service.py`
- Modify: `backend/tests/test_audit_runner_quality.py`
- Modify: `backend/tests/test_contract_quality_api.py`
- Modify: `backend/tests/test_merge_readiness_unittest.py`

- [ ] **Step 1: 写失败测试，锁定新状态机和批次汇总**

在 `test_batch_service.py` 增加：

```python
def test_review_required_is_terminal_but_not_failed():
    progress = summarize(["done", "review_required"])
    assert progress.completed == 2
    assert progress.failed == 0
    assert progress.status == "review_required"


def test_item_transitions_through_review_and_validation():
    assert transition_item("parsing", "reviewing") == "reviewing"
    assert transition_item("reviewing", "validating") == "validating"
    assert transition_item("validating", "review_required") == "review_required"
    with pytest.raises(InvalidBatchTransition):
        transition_item("reviewing", "done")
```

在 `test_audit_runner_quality.py` 增加：局部失败且存在可用风险时发布已验证风险并设置合同/批次项为 `review_required`；全部窗口失败时不发布新风险且设置 `audit_failed/failed`；质量完全通过才设置 `done`。在 `test_merge_readiness_unittest.py` 增加 worker 从 `reviewing`、`validating` 租约过期状态恢复的测试。

- [ ] **Step 2: 运行状态机、Runner 与 API 测试并确认失败**

Run:

```powershell
Set-Location backend
.\.venv\Scripts\python.exe -m pytest tests\test_batch_service.py tests\test_audit_runner_quality.py tests\test_contract_quality_api.py tests\test_merge_readiness_unittest.py -q
```

Expected: FAIL，`reviewing`、`validating`、`review_required` 尚未进入状态集合和响应字面量。

- [ ] **Step 3: 扩展状态机并明确聚合规则**

`service.py` 调整为：

```python
BATCH_STATUSES = frozenset({
    "queued", "running", "done", "review_required", "partial_failed", "failed",
})
ITEM_STATUSES = frozenset({
    "queued", "parsing", "reviewing", "validating",
    "done", "review_required", "failed",
})
TERMINAL_ITEM_STATUSES = frozenset({"done", "review_required", "failed"})
ALLOWED_TRANSITIONS = {
    "queued": frozenset({"parsing", "failed"}),
    "parsing": frozenset({"reviewing", "failed"}),
    "reviewing": frozenset({"validating", "failed"}),
    "validating": frozenset({"done", "review_required", "failed"}),
    "failed": frozenset({"queued"}),
    "done": frozenset(),
    "review_required": frozenset(),
}
```

聚合优先级：未终止项存在则 `running`；全部 `done` 为 `done`；没有 `failed` 且至少一个 `review_required` 为 `review_required`；全部 `failed` 为 `failed`；其余为 `partial_failed`。`completed` 包含三个终态，`failed` 只统计真正失败项。

- [ ] **Step 4: 让 Runner 以质量决定原子发布**

`run_audit()` 将实际 `claimed_generation` 传给 `audit_contract()`。候选审查计算完成后，先在独立短事务中重新校验 generation/execution token，将合同和批次项更新为 `validating` 并提交，使该阶段可被轮询观察；随后执行最终质量判定，并在发布事务中：

1. 再次校验 generation 与 execution token；
2. 将解析质量问题转换为 `PARSE_QUALITY_LOW` 或 `CONTRACT_TEXT_INCOMPLETE` issue 后一并判定；
3. `done/review_required` 才替换本 generation 的正式风险；
4. `audit_failed` 不删除上一 generation 的已发布风险；
5. 把 `issues/coverage/quality_reasons` 写入 `AuditBatchItem.result_json`，不写模型正文；
6. 同一事务更新 `Contract.status`、`requires_review`、`review_reason` 和批次项终态。

面向调用方返回真实终态：

```python
return {
    "risk_count": len(published_risks),
    "cross_checks": cross_checks,
    "status": decision.status,
    "requires_review": decision.requires_review,
    "review_reason": quality_reason_text(decision.reasons),
    "quality_reasons": list(decision.reasons),
    "coverage": coverage,
}
```

`run_contract_audit()` 不再硬编码返回 `status: "done"`。`classify_task_error()` 直接使用 `LLMError.code/retryable`，不再解析中文异常文本。恢复查询覆盖 `parsing/reviewing/validating`；旧 `auditing` 已在迁移中归一化。

- [ ] **Step 5: 对齐 Schema 和状态 API**

`BatchStatus` 增加 `review_required`；`BatchItemStatus` 改为上述七个精确字面量。`AuditResponse` 增加：

```python
quality_reasons: list[str] = Field(default_factory=list)
coverage: dict[str, int] | None = None
```

`get_contract_audit_status()` 以 `AuditBatchItem.result_json` 为运行结果事实来源，将批次项 `failed` 映射为合同响应的 `audit_failed`，原样返回 `review_required`；不得再把 `requires_review=True` 与 `done` 同时返回。批次响应继续使用 ORM 属性，不新增第二套状态推导。

- [ ] **Step 6: 运行后端状态、恢复与 API 回归测试**

Run:

```powershell
Set-Location backend
.\.venv\Scripts\python.exe -m pytest tests\test_batch_service.py tests\test_audit_job_service.py tests\test_audit_runner_quality.py tests\test_contract_quality_api.py tests\test_batch_api.py tests\test_merge_readiness_unittest.py -q
```

Expected: PASS；`done` 响应不含质量问题，局部问题稳定返回 `review_required`，无可用结果稳定返回 `audit_failed`。

- [ ] **Step 7: 提交状态语义**

```powershell
git add backend/app/services/audit/runner.py backend/app/tasks/audit_tasks.py backend/app/services/batch/service.py backend/app/schemas/batch.py backend/app/schemas/contract.py backend/app/api/v1/endpoints/contracts.py backend/app/api/v1/endpoints/batches.py backend/tests/test_batch_service.py backend/tests/test_audit_job_service.py backend/tests/test_audit_runner_quality.py backend/tests/test_contract_quality_api.py backend/tests/test_merge_readiness_unittest.py
git commit -m "feat: publish audit quality states accurately"
```

### Task 7: 增加选择性二次复核

**Files:**
- Create: `backend/app/services/audit/secondary_review.py`
- Modify: `backend/app/services/audit/auditor.py:129-211`
- Modify: `backend/app/services/audit/protocol.py`
- Modify: `backend/app/services/audit/result_quality.py`
- Create: `backend/tests/test_secondary_review.py`
- Modify: `backend/tests/test_audit_result_quality.py`
- Modify: `backend/tests/test_audit_evidence.py`

- [ ] **Step 1: 写失败测试，证明只复核必要项目**

```python
def test_only_high_conflict_and_decidable_evidence_items_call_secondary_model():
    adapter = QueueAdapter([secondary_confirm("high-1"), secondary_reject("conflict-1")])
    reviewer = SecondaryReviewer(adapter)
    result = reviewer.review(
        risks=[
            risk("low-ok", level="low", evidence_status="supported"),
            risk("high-1", level="high", evidence_status="supported"),
            risk("conflict-1", level="medium", evidence_status="supported"),
            risk("no-evidence", level="medium", evidence_ids=[]),
        ],
        conflict_claim_ids={"conflict-1"},
    )

    assert [call.claim_id for call in adapter.calls] == ["high-1", "conflict-1"]
    assert result.by_claim["low-ok"].status == "not_required"
    assert result.by_claim["no-evidence"].status == "manual_required"
```

再测试：二次模型与主审冲突时保留原候选但产生 `SECONDARY_REVIEW_CONFLICT`；二次模型明确拒绝时不发布该候选；二次模型超时只影响被选中的候选，不重放已完成窗口。

- [ ] **Step 2: 运行二次复核测试并确认失败**

Run: `backend\.venv\Scripts\python.exe -m pytest backend\tests\test_secondary_review.py -q`

Expected: FAIL with `ModuleNotFoundError: app.services.audit.secondary_review`。

- [ ] **Step 3: 完成严格复核协议与选择器**

`protocol.py` 中 `SecondaryDecision` 只允许：

```python
class SecondaryDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    claim_id: str = Field(min_length=8, max_length=64)
    verdict: Literal["confirm", "reject", "conflict"]
    reason: str = Field(min_length=4, max_length=500)
    evidence_ids: list[str] = Field(default_factory=list, max_length=8)
```

`select_secondary_candidates()` 只选择 `level=high`、命中确定性冲突或跨 Agent 冲突、以及已有候选证据但支持关系为 `unclear/contradicted` 的风险。`evidence_ids=[]` 的项目直接标记 `manual_required`，不得为了“试试看”调用模型。

- [ ] **Step 4: 实现批内逐项复核和决定应用**

```python
class SecondaryReviewer:
    def review(
        self,
        *,
        risks: Sequence[Mapping[str, object]],
        conflict_claim_ids: set[str],
    ) -> SecondaryReviewResult:
        selected, immediate = select_secondary_candidates(risks, conflict_claim_ids)
        decisions = dict(immediate)
        for risk in selected:
            decisions[risk["claim_id"]] = self._review_one(risk)
        return SecondaryReviewResult(by_claim=decisions)
```

复核 prompt 只包含候选风险、已精确定位的原文和系统已授权的证据 ID/摘要；模型不得返回新法规、自由文本条号或新的风险。调用继续通过 `ChatOptions(response_format=AUDIT_JSON_FORMAT)` 并记录 `agent="secondary"`。

`apply_secondary_decisions()` 的规则固定为：`confirm` 保留并标记 `confirmed`；`reject` 从正式风险集移除但保留调用日志；`conflict` 保留并标记 `conflict`、产生 issue；`manual_required` 保留并强制进入人工复核；未选中项标记 `not_required`。

- [ ] **Step 5: 在 audit_contract 中接入且重新计算质量状态**

主审 Agent、确定性检查和证据校验全部完成后才调用 `SecondaryReviewer`。将复核后的风险与新增 issues 返回 Runner；`result_quality` 将 `conflict/manual_required` 判为 `review_required`。不得因为一条复核失败把其他已验证候选丢弃。

- [ ] **Step 6: 运行二次复核与端到端后端回归测试**

Run:

```powershell
Set-Location backend
.\.venv\Scripts\python.exe -m pytest tests\test_secondary_review.py tests\test_audit_result_quality.py tests\test_audit_evidence.py tests\test_audit_runner_quality.py tests\test_contract_logic.py -q
```

Expected: PASS；普通低/中风险不产生额外模型调用；无证据项不产生模型调用。

- [ ] **Step 7: 提交选择性复核**

```powershell
git add backend/app/services/audit/secondary_review.py backend/app/services/audit/auditor.py backend/app/services/audit/protocol.py backend/app/services/audit/result_quality.py backend/tests/test_secondary_review.py backend/tests/test_audit_result_quality.py backend/tests/test_audit_evidence.py
git commit -m "feat: add selective secondary audit review"
```

### Task 8: 前端准确展示审查状态与人工复核

**Files:**
- Modify: `frontend/src/api/types.ts:12-79`
- Modify: `frontend/src/stores/batch.ts:1-190`
- Modify: `frontend/src/views/AuditView.vue:174-191,330-371,1090-1110`
- Modify: `frontend/tests/batch-store.spec.ts`
- Create: `frontend/tests/audit-quality-state-e2e.spec.ts`

- [ ] **Step 1: 写失败测试，锁定轮询终态和用户可见语义**

在 `batch-store.spec.ts` 增加：

```typescript
test('review_required is terminal and does not count as failed', async () => {
  const useStore = createBatchStore(fakeApi([
    batch('review_required', ['done', 'review_required']),
  ]))
  const store = useStore()
  store.polling = true

  await store.pollOnce(1)

  expect(store.polling).toBe(false)
  expect(store.batch?.failed).toBe(0)
})
```

`audit-quality-state-e2e.spec.ts` mock API 分别返回 `reviewing`、`validating`、`review_required`、`failed`，断言页面标签依次为“审查中”“结果校验中”“需人工复核”“失败”；`review_required` 项显示原因和查看结果按钮，不显示“重试失败项”。

- [ ] **Step 2: 运行前端测试并确认类型或断言失败**

Run:

```powershell
Set-Location frontend
npm.cmd test -- tests/batch-store.spec.ts tests/audit-quality-state-e2e.spec.ts
```

Expected: FAIL，现有联合类型、终态集合和标签映射不认识新状态。

- [ ] **Step 3: 收紧 API 类型与轮询规则**

在 `types.ts` 导出：

```typescript
export type AuditItemStatus =
  | 'queued' | 'parsing' | 'reviewing' | 'validating'
  | 'done' | 'review_required' | 'failed'
export type AuditBatchStatus =
  | 'queued' | 'running' | 'done' | 'review_required'
  | 'partial_failed' | 'failed'
```

让 `ContractOut.status`、`AuditResult.status` 和批次类型使用精确联合类型；为风险类型增加 `secondary_review_status`、`secondary_review_reason`。`TERMINAL_STATUSES` 加入 `review_required`，进度仍以服务端 `completed/total` 为准，不在前端重复推断。

- [ ] **Step 4: 更新批次展示和可执行操作**

状态标签增加：

```typescript
const batchStatusLabel = {
  queued: '等待审查', running: '审查中', done: '已完成',
  review_required: '需人工复核', partial_failed: '部分失败', failed: '审查失败',
} as const

const batchItemStatusLabel = {
  queued: '等待中', parsing: '解析中', reviewing: '审查中',
  validating: '结果校验中', done: '已完成',
  review_required: '需人工复核', failed: '失败',
} as const
```

`review_required` 使用 warning 标签，显示 `review_reason`，并允许进入历史页核对部分结果；只有 `failed > 0` 才显示重试按钮。空批次维持现有引导，API 错误维持现有错误提示；在 375px 宽度下批次文件名、状态和查看按钮换行但不重叠。

- [ ] **Step 5: 运行前端单测、类型检查和构建**

Run:

```powershell
Set-Location frontend
npm.cmd test -- tests/batch-store.spec.ts tests/audit-quality-state-e2e.spec.ts
npm.cmd run type-check
npm.cmd run build
```

Expected: 全部 PASS，Vite 构建退出码为 0。

- [ ] **Step 6: 浏览器实测正常、空、错误、恢复和响应式状态**

启动后端与前端，在 Playwright 中验证：正常批次从 `reviewing -> validating -> done`；空状态仍可开始导入；请求失败显示错误；刷新后恢复轮询；`review_required` 可查看原因与结果；桌面 1440×900 和移动 375×812 无遮挡、溢出和不可点击控件。

- [ ] **Step 7: 提交前端状态支持**

```powershell
git add frontend/src/api/types.ts frontend/src/stores/batch.ts frontend/src/views/AuditView.vue frontend/tests/batch-store.spec.ts frontend/tests/audit-quality-state-e2e.spec.ts
git commit -m "feat: show reliable audit quality states"
```

### Task 9: 建立审查质量与成本 A/B 评测

**Files:**
- Create: `backend/evaluation/audit_quality.py`
- Create: `backend/evaluation/audit_comparison.py`
- Modify: `backend/evaluation/cli.py:1-470`
- Modify: `backend/evaluation/report.py:13-397`
- Create: `backend/tests/test_audit_quality_metrics.py`
- Create: `backend/tests/test_audit_comparison.py`
- Modify: `backend/tests/test_evaluation_cli.py`
- Modify: `backend/tests/test_evaluation_report.py`

- [ ] **Step 1: 写失败测试，质量未过门槛时禁止选“最优”**

`test_audit_quality_metrics.py`：

```python
def test_false_success_counts_done_with_truncation_or_incomplete_coverage():
    report = evaluate_audit_dataset(
        gold=[gold_case("c-1", high_risks={"g-1"})],
        predictions=[prediction(
            "c-1",
            status="done",
            matched_gold_ids={"g-1"},
            finish_reasons=["length"],
            coverage=(1, 2),
        )],
    )
    assert report["overall"]["false_success_rate"] == 1.0
    assert report["overall"]["final_truncation_rate"] == 1.0
```

`test_audit_comparison.py`：

```python
def test_comparison_rejects_cheaper_candidate_below_quality_gate():
    cheap = candidate("cheap", high_recall=.80, cost_per_success=0.01)
    reliable = candidate("reliable", high_recall=.97, cost_per_success=0.05)

    result = compare_audit_candidates([cheap, reliable])

    assert result.selected == "reliable"
    assert result.rejected["cheap"] == ["high_risk_recall"]


def test_comparison_makes_no_claim_when_no_candidate_passes():
    result = compare_audit_candidates([candidate("a", false_success_rate=.1)])
    assert result.selected is None
    assert result.status == "failed"
```

- [ ] **Step 2: 运行评测测试并确认模块不存在**

Run:

```powershell
Set-Location backend
.\.venv\Scripts\python.exe -m pytest tests\test_audit_quality_metrics.py tests\test_audit_comparison.py -q
```

Expected: FAIL，缺少两个评测模块。

- [ ] **Step 3: 实现可审计的质量指标**

`audit_quality.py` 读取人工金标准与预测 JSONL。金标准风险必须包含稳定 `gold_risk_id`、等级、类别、原文位置和证据 ID；预测文件必须包含人工裁定后的 `matched_gold_id` 或 `null`。评测器拒绝重复匹配和未知 gold ID，不用模型做语义裁判。

输出至少包含：

```python
overall = {
    "high_risk_recall": high_tp / high_gold,
    "risk_recall": tp / gold_count,
    "risk_precision": tp / predicted_count,
    "quote_location_rate": located / predicted_count,
    "invalid_legal_citation_rate": invalid_citations / predicted_count,
    "json_valid_rate": valid_json_calls / total_calls,
    "final_truncation_rate": truncated_contracts / contract_count,
    "false_success_rate": false_done / done_count,
    "manual_review_rate": review_required / contract_count,
    "mean_prompt_tokens": prompt_tokens / contract_count,
    "mean_completion_tokens": completion_tokens / contract_count,
    "mean_cost_per_success": total_cost / successful_contracts,
    "p95_latency_ms": percentile(latencies, .95),
}
```

分母为 0 时返回 `None` 并使质量门槛失败，不用 0 或 1 掩盖空样本。成本输入必须同时提供 `currency`、`pricing_source`、`pricing_version` 和逐调用计费金额；缺任一项时 `mean_cost_per_success=None`。报告包含 `sample_count`、逐合同指标和输入哈希，但不包含合同正文、prompt 或模型响应。

- [ ] **Step 4: 实现先质量、后成本的比较器**

`audit_comparison.py` 固定门槛：高风险召回率 `>=0.95`、错误成功率 `0`、最终截断率 `0`、原文可定位率 `1`、无效法规引用率 `0`、整体召回率 `>=0.90`、精确率 `>=0.85`、JSON 合法率 `1`。先排除未通过任一 P1/P2 门槛的候选，再按：

1. 每份成功合同实际成本；
2. 平均总 tokens；
3. P95 延迟；

升序选择。任何关键成本字段缺失时只输出“质量通过、成本结论不足”，不得宣称最具性价比。

- [ ] **Step 5: 接入 CLI、EvidenceWriter 和报告校验**

新增命令：

```powershell
python -m evaluation.cli audit-quality --gold GOLD.jsonl --predictions PREDICTIONS.jsonl --runs-root evaluation-runs
python -m evaluation.cli audit-compare --candidate A=RUN_A/audit-summary.json --candidate B=RUN_B/audit-summary.json --candidate C=RUN_C/audit-summary.json --runs-root evaluation-runs
```

`report.py` 的 `_STREAMS` 增加 `audit: audit.jsonl`、`audit_comparison: audit-comparison.jsonl`，并严格校验 manifest 输入哈希、样本数、门槛结果和 selected 值的一致性。Markdown 明确写“合成数据技术预评测”或“人工金标准评测”，不得把 construction truth 写成人工准确率结论。

基线 A 固定为代码提交 `94c8f9f`；B 为仅提高输出预算的临时评测配置；C 为本计划实现。三组使用同一模型版本、prompt 版本、知识库版本、合成合同集、温度和运行环境。生产代码不增加 legacy 开关；A/B 通过独立 Git worktree 运行。

- [ ] **Step 6: 运行评测、CLI 与报告测试**

Run:

```powershell
Set-Location backend
.\.venv\Scripts\python.exe -m pytest tests\test_audit_quality_metrics.py tests\test_audit_comparison.py tests\test_evaluation_cli.py tests\test_evaluation_report.py -q
```

Expected: PASS；测试数据全部为本地合成 JSONL，不调用公网模型。

- [ ] **Step 7: 提交评测闭环**

```powershell
git add backend/evaluation/audit_quality.py backend/evaluation/audit_comparison.py backend/evaluation/cli.py backend/evaluation/report.py backend/tests/test_audit_quality_metrics.py backend/tests/test_audit_comparison.py backend/tests/test_evaluation_cli.py backend/tests/test_evaluation_report.py
git commit -m "feat: evaluate audit quality and cost"
```

### Task 10: 完整验收并形成有边界的结论

**Files:**
- Verify only: files changed in Tasks 1-9
- Evidence output, do not commit: `backend/evaluation-runs/<run-id>/`
- Browser evidence, do not commit: `outputs/audit-quality-ui/`
- Create: `docs/superpowers/reports/2026-09-13-llm-audit-reliability-verification.md`

- [ ] **Step 1: 运行后端目标回归**

```powershell
Set-Location backend
.\.venv\Scripts\python.exe -m pytest tests\test_llm_adapter.py tests\test_audit_protocol.py tests\test_review_pipeline.py tests\test_audit_window_repository.py tests\test_audit_result_quality.py tests\test_secondary_review.py tests\test_audit_evidence.py tests\test_audit_runner_quality.py tests\test_batch_service.py tests\test_contract_quality_api.py -q
```

Expected: PASS，且测试日志没有真实合同正文、prompt、响应正文或密钥。

- [ ] **Step 2: 运行前端测试、类型检查与构建**

```powershell
Set-Location frontend
npm.cmd test -- tests/batch-store.spec.ts tests/audit-quality-state-e2e.spec.ts tests/audit-reliability-e2e.spec.ts
npm.cmd run type-check
npm.cmd run build
```

Expected: 全部 PASS，构建退出码 0。

- [ ] **Step 3: 运行项目完整质量门禁**

```powershell
Set-Location ..
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\quality_gate.ps1
```

Expected: 所有既有 evaluation、backend、frontend 步骤通过。若门禁暴露与本计划变更有关的失败，回到对应任务按 RED/GREEN 修复并单独提交；不得跳过失败步骤。

- [ ] **Step 4: 启动服务并做浏览器实测**

```powershell
Set-Location backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000

Set-Location ..\frontend
npm.cmd run dev -- --host 127.0.0.1 --port 5173
```

用合成合同验证正常、无风险、截断恢复、非法 JSON、模型超时、证据不足、冲突、刷新恢复和移动端状态。确认任何截断或局部失败都不能显示“已完成”，`review_required` 可看到原因及已验证结果，`audit_failed` 不展示本次伪结果。

- [ ] **Step 5: 经确认后运行真实公网模型 A/B**

这是有费用和数据外发风险的操作，执行者必须先向用户说明模型提供方、预计调用量/费用、合成数据范围和密钥环境变量，并取得明确确认。只使用无敏感信息的合成合同；禁止上传真实合同。

按 A=`94c8f9f`、B=仅提高预算、C=选择性级联三组各生成预测与调用观测，随后运行 `audit-quality` 和 `audit-compare`。若没有人工金标准，仅可标注“合成数据技术预评测”，不可写“准确率达标”。

- [ ] **Step 6: 审核最终声明边界**

只有 `audit-compare` 选出候选，且其所有 P1/P2 指标通过、成本字段完整时，才可写“在本次冻结模型、数据集和环境下最具性价比”。否则按实际结果写“首选候选架构”“质量未达门槛”或“成本证据不足”。不得外推到真实 52 文件、PostgreSQL、OCR、OpenClaw/GPU 或能耗指标。

- [ ] **Step 7: 写入非敏感验证摘要**

创建 `docs/superpowers/reports/2026-09-13-llm-audit-reliability-verification.md`，只记录：验证时间、Git 提交、工作区是否干净、各命令退出码与测试计数、浏览器视口/状态覆盖、评测输入 SHA-256、A/B 是否执行、门槛结果和结论边界。不得复制合同正文、prompt、响应正文、密钥、绝对用户目录或数据库内容。

真实 A/B 未获授权或尚未运行时必须写 `status: blocked` 或 `status: not_run` 及原因；只有 `audit-compare` 实际选出候选时才记录选中配置。

- [ ] **Step 8: 核对边界并提交验证摘要**

```powershell
git status --short
git diff --check
git log --oneline -9
git add docs/superpowers/reports/2026-09-13-llm-audit-reliability-verification.md
git commit -m "docs: record reliable audit verification"
```

Expected: `git diff --check` 无输出；Tasks 1-9 各有独立提交；Task 10 只提交验证摘要；不提交 `.env`、数据库、日志、`outputs/`、`evaluation-runs/`、模型缓存或真实合同。若验收产生代码修复，回到对应任务重新运行该任务的 GREEN 命令并以明确文件清单提交，不创建无法归属的笼统“最终修复”提交。
