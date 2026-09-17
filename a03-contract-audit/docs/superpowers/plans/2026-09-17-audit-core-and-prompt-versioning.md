# 审查内核与提示词版本化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改变现有 API 的前提下建立版本化 Claim、提示词注册表和法务/财务独立首审流程。

**Architecture:** 保留 `audit_contract()` 兼容入口，将角色配置、提示词构建、Claim 标准化和双 Agent 调度拆成独立模块。两个 Agent 首审时互不可见，首审结束后才通过结构化 Claim 进行交叉复核。

**Tech Stack:** Python 3.11、FastAPI、Pydantic v2、SQLAlchemy、pytest。

---

## 执行约定

以下命令从仓库外层目录执行，运行 pytest 前设置 `$env:PYTHONPATH=(Resolve-Path 'a03-contract-audit/backend').Path`。所有 Python 路径以 `a03-contract-audit/backend/` 开头；`git commit` 前只暂存当前任务 Files 清单中的本轮修改，不使用 `git add .`。现有用户改动必须保留。

本计划中的最小代码用于固定接口和可观察行为；实现必须包含展示代码所需的标准库、Pydantic 和项目模块导入，不新增运行依赖。测试 fixture 在各任务中定义，不依赖未提供的全局测试辅助库。

## 文件结构

- Create: `backend/app/services/audit/claims.py`：内部 Claim 契约和稳定 ID。
- Create: `backend/app/services/audit/agent_profiles.py`：角色、维度和复核路由配置。
- Create: `backend/app/services/audit/prompts/registry.py`：Prompt ID、版本、哈希和模板选择。
- Create: `backend/app/services/audit/prompts/review.py`：发现、补全和交叉复核模板。
- Create: `backend/app/services/audit/collaboration.py`：独立首审结果和结构化交接。
- Modify: `backend/app/services/audit/auditor.py`：保留兼容入口，委托新模块。
- Modify: `backend/app/services/audit/protocol.py`：增加 Claim Schema 和原因码。
- Test: `backend/tests/test_audit_claims.py`。
- Test: `backend/tests/test_audit_prompts.py`。
- Test: `backend/tests/test_audit_collaboration.py`。
- Modify: `backend/tests/test_audit_evidence.py`。

### Task 1: 建立内部 Claim 契约

- [ ] **Step 1: 写入失败测试**

```python
from app.services.audit.claims import AuditClaim, claim_id_for


def test_claim_id_is_stable_and_quote_is_required():
    claim = AuditClaim(
        agent="legal", level="high", category="付款条件不明确",
        dimension="payment", subject="甲方", action="支付尾款",
        condition="验收完成", consequence="支付20%合同款",
        quote="验收完成后支付剩余款项", clause_ids=["C-18"],
        missing_information=["付款期限"], review_targets=["finance"],
    )
    assert claim.claim_id == claim_id_for(claim)
    assert claim.model_dump(mode="json")["schema_version"] == "claim-v1"
```

- [ ] **Step 2: 运行红灯测试**

Run: `a03-contract-audit/backend/.venv/Scripts/python.exe -m pytest a03-contract-audit/backend/tests/test_audit_claims.py -q`

Expected: FAIL，提示 `app.services.audit.claims` 不存在。

- [ ] **Step 3: 创建最小实现**

```python
CLAIM_SCHEMA_VERSION = "claim-v1"

class AuditClaim(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    schema_version: Literal["claim-v1"] = CLAIM_SCHEMA_VERSION
    claim_id: str = ""
    agent: Literal["legal", "finance", "system"]
    level: Literal["high", "medium", "low"]
    category: str
    dimension: str
    subject: str = ""
    action: str = ""
    condition: str = ""
    consequence: str = ""
    quote: str
    clause_ids: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    review_targets: list[Literal["legal", "finance"]] = Field(default_factory=list)

    @model_validator(mode="after")
    def assign_claim_id(self) -> Self:
        if not self.claim_id:
            self.claim_id = claim_id_for(self)
        return self

def claim_id_for(claim: AuditClaim) -> str:
    raw = "\0".join((claim.agent, claim.category, claim.dimension, claim.quote))
    return "C-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16].upper()
```

- [ ] **Step 4: 运行测试并提交**

Run: `a03-contract-audit/backend/.venv/Scripts/python.exe -m pytest a03-contract-audit/backend/tests/test_audit_claims.py -q`

Expected: PASS。

Commit: `git commit -m "feat: add versioned audit claim contract"`

### Task 2: 提取角色配置与提示词注册表

- [ ] **Step 1: 编写注册表失败测试**

```python
from app.services.audit.prompts.registry import get_prompt


def test_prompt_registry_returns_versioned_template_and_stable_hash():
    prompt = get_prompt("legal.discovery", "2.0.0")
    assert prompt.prompt_id == "legal.discovery"
    assert prompt.version == "2.0.0"
    assert len(prompt.template_sha256) == 64
    assert "不得生成法规依据" in prompt.system
```

- [ ] **Step 2: 运行红灯测试**

Run: `a03-contract-audit/backend/.venv/Scripts/python.exe -m pytest a03-contract-audit/backend/tests/test_audit_prompts.py -q`

Expected: FAIL，提示 Prompt Registry 不存在。

- [ ] **Step 3: 实现不可变注册表**

```python
@dataclass(frozen=True)
class PromptTemplate:
    prompt_id: str
    version: str
    system: str

    @property
    def template_sha256(self) -> str:
        return hashlib.sha256(self.system.encode("utf-8")).hexdigest()

_PROMPTS = {
    ("legal.discovery", "2.0.0"): PromptTemplate(
        "legal.discovery", "2.0.0", LEGAL_DISCOVERY_SYSTEM,
    ),
    ("finance.discovery", "2.0.0"): PromptTemplate(
        "finance.discovery", "2.0.0", FINANCE_DISCOVERY_SYSTEM,
    ),
}

def get_prompt(prompt_id: str, version: str) -> PromptTemplate:
    try:
        return _PROMPTS[(prompt_id, version)]
    except KeyError as exc:
        raise ValueError(f"未知提示词版本: {prompt_id}@{version}") from exc
```

将 `_AGENTS`、`_ROLE_DIMENSIONS` 和 `_DIM_TOPICS` 移入 `agent_profiles.py`；`auditor.py` 从新模块导入，不改变字段内容。

- [ ] **Step 4: 验证提示词边界与现有输出协议**

Run: `a03-contract-audit/backend/.venv/Scripts/python.exe -m pytest a03-contract-audit/backend/tests/test_audit_prompts.py a03-contract-audit/backend/tests/test_audit_protocol.py a03-contract-audit/backend/tests/test_review_pipeline.py -q`

Expected: PASS。

Commit: `git commit -m "refactor: version audit prompts and agent profiles"`

### Task 3: 将模型发现结果标准化为 Claim

- [ ] **Step 1: 添加标准化失败测试**

```python
def test_normalize_finding_preserves_agent_window_and_clause_ids():
    finding = RiskFinding(level="medium", category="付款期限", quote="验收后付款")
    claim = normalize_finding(
        finding, agent="finance", dimension="payment",
        window_id="window-1", clause_ids=("第三条",),
    )
    assert claim.agent == "finance"
    assert claim.dimension == "payment"
    assert claim.clause_ids == ["第三条"]
```

在 `claims.py` 定义 `normalize_finding(finding, *, agent, dimension, window_id, clause_ids) -> AuditClaim`；`AuditClaim` 增加 `source_window_id: str | None = None`。该函数直接将传入值映射到 Claim，不调用模型。

- [ ] **Step 2: 运行红灯，随后实现 `normalize_finding()`**

Run: `a03-contract-audit/backend/.venv/Scripts/python.exe -m pytest a03-contract-audit/backend/tests/test_audit_claims.py::test_normalize_finding_preserves_agent_window_and_clause_ids -q`

Implementation requirement: 未经模型明确输出的主体、条件和后果保持空字符串；不得从类别名称臆造事实；`source_window_id` 作为内部追踪字段保留。

- [ ] **Step 3: 在 `auditor.py` 兼容转换**

`_agent_audit()` 继续向现有调用者返回风险字典，但先生成 `AuditClaim`，再由单一适配函数映射到现有 `claim_id`、`source_window_id`、`source_clause_ids` 和风险字段，删除重复 ID 生成逻辑。

- [ ] **Step 4: 运行回归并提交**

Run: `a03-contract-audit/backend/.venv/Scripts/python.exe -m pytest a03-contract-audit/backend/tests/test_audit_claims.py a03-contract-audit/backend/tests/test_audit_two_stage.py a03-contract-audit/backend/tests/test_audit_evidence.py -q`

Expected: PASS，现有 API 字段不变。

Commit: `git commit -m "refactor: normalize model findings as audit claims"`

### Task 4: 法务与财务独立首审

- [ ] **Step 1: 将现有锚定行为测试改为独立性测试**

```python
def test_finance_first_pass_does_not_receive_legal_claims(monkeypatch):
    from app.llm.base import LLMResponse
    prompts = []

    class Adapter:
        def chat(self, system, user, **kwargs):
            prompts.append((system, user))
            return LLMResponse(text='{"risks":[],"has_more":false}', model="test")

    monkeypatch.setattr(auditor, "get_llm_adapter", lambda: Adapter())
    monkeypatch.setattr(auditor, "retrieve", lambda *args, **kwargs: [])
    auditor.audit_contract({}, "第一条 关联方提供服务。")
    finance_first_pass = next(user for system, user in prompts if "你是财务" in system)
    assert "法务 Agent 已完成" not in finance_first_pass
    assert "结构化 Claims" not in finance_first_pass
```

- [ ] **Step 2: 运行测试确认红灯**

Run: `a03-contract-audit/backend/.venv/Scripts/python.exe -m pytest a03-contract-audit/backend/tests/test_audit_collaboration.py::test_finance_first_pass_does_not_receive_legal_claims -q`

Expected: FAIL，当前财务提示词包含法务共享上下文。

除空候选测试外，保留现有 `test_agent_failure_preserves_other_agents_verified_risk_and_shared_context` 的合法关联交易候选 fixture，断言财务首审不含该候选、首审结束后的交接才包含对应 Claim ID；前者是防注入隔离测试，后者证明真实候选不会产生锚定。

- [ ] **Step 3: 实现独立首审协调器**

```python
@dataclass(frozen=True)
class FirstPassBundle:
    legal: AgentAuditResult
    finance: AgentAuditResult

def first_pass(run_agent: Callable[[str], AgentAuditResult]) -> FirstPassBundle:
    return FirstPassBundle(
        legal=run_agent("legal"),
        finance=run_agent("finance"),
    )
```

移除财务首审 `upstream_block`。付款比例等确定性事实可以同时提供给两个 Agent，但不得携带另一 Agent 的判断。为了保持事务和检查点安全，本阶段先顺序执行两个独立首审；并行化属于性能优化，不与语义改造同批实施。

- [ ] **Step 4: 增加结构化交接**

```python
@dataclass(frozen=True)
class ReviewHandoff:
from_agent: str
    to_agent: str
    claim_ids: tuple[str, ...]
    reason_codes: tuple[str, ...]
```

只把 `claim_id`、类别、条款 ID、确定性事实和受控原因码传给交叉复核；不传递自由推理文本。

- [ ] **Step 5: 验证并提交**

Run: `a03-contract-audit/backend/.venv/Scripts/python.exe -m pytest a03-contract-audit/backend/tests/test_audit_collaboration.py a03-contract-audit/backend/tests/test_audit_evidence.py a03-contract-audit/backend/tests/test_secondary_review.py -q`

Expected: PASS，单个 Agent 失败仍保留另一 Agent 已验证结果。

Commit: `git commit -m "feat: isolate legal and finance first-pass review"`

### Task 5: 完成本阶段回归门禁

- [ ] **Step 1: 运行审查子系统回归**

Run: `a03-contract-audit/backend/.venv/Scripts/python.exe -m pytest a03-contract-audit/backend/tests/test_audit_protocol.py a03-contract-audit/backend/tests/test_review_pipeline.py a03-contract-audit/backend/tests/test_audit_two_stage.py a03-contract-audit/backend/tests/test_audit_evidence.py a03-contract-audit/backend/tests/test_secondary_review.py a03-contract-audit/backend/tests/test_audit_window_repository.py -q`

Expected: 全部 PASS。

- [ ] **Step 2: 检查兼容性和代码质量**

Run: `git diff --check`

Run: `powershell -NoProfile -ExecutionPolicy Bypass -File a03-contract-audit/scripts/quality_gate.ps1`

Expected: 退出码 0。若工作区存在其他未完成改动，记录受影响门禁，不把失败归因于本计划。

- [ ] **Step 3: 提交阶段验收**

Commit: `git commit -m "test: verify versioned independent audit agents"`
