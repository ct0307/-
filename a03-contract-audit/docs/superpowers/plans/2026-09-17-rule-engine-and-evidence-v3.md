# 规则引擎与证据支持 V3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将硬编码确定性检查升级为版本化规则引擎，并以原文、权威性、适用性、事实一致性和语义关系五层门禁生成最终风险决策。

**Architecture:** 规则引擎只消费标准化事实并输出受控原因码；支持关系验证器依次执行硬门禁，语义判断不能覆盖硬门禁失败；最终决策由纯函数统一映射。

**Tech Stack:** Python 3.11、Pydantic v2、SQLAlchemy、Alembic、pytest。

---

## 执行约定

以下命令从仓库外层目录执行，运行 pytest 前设置 `$env:PYTHONPATH=(Resolve-Path 'a03-contract-audit/backend').Path`。只暂存当前任务 Files 清单中的本轮修改，不使用 `git add .`。本计划以前两阶段的 Claim、查询轨迹和适用性结果为输入；前置测试不通过时停止实施。

规则定义使用项目内 JSON 和 Python，不安装规则引擎依赖。迁移只追加保守默认字段，不回写历史合同结论。

## 文件结构

- Create: `backend/app/services/audit/rules/schema.py`。
- Create: `backend/app/services/audit/rules/registry.py`。
- Create: `backend/app/services/audit/rules/executor.py`。
- Create: `backend/app/services/audit/rules/handlers/completeness.py`。
- Create: `backend/app/services/audit/rules/handlers/payment.py`。
- Create: `backend/app/services/audit/rules/handlers/amount.py`。
- Create: `backend/app/services/audit/rules/handlers/cross_clause.py`。
- Create: `backend/app/services/audit/rules/definitions/legal.json`。
- Create: `backend/app/services/audit/rules/definitions/finance.json`。
- Create: `backend/app/services/audit/decision.py`。
- Modify: `backend/app/services/audit/deterministic_checks.py`。
- Modify: `backend/app/services/audit/evidence_validation.py`。
- Modify: `backend/app/models/models.py`、`backend/app/schemas/contract.py`、`backend/app/services/audit/runner.py`。
- Create: `backend/alembic/versions/20260917_02_audit_decision_trace.py`。
- Test: `backend/tests/test_rule_registry.py`、`test_rule_executor.py`、`test_evidence_support_v3.py`、`test_risk_decision.py`。

### Task 1: 定义规则契约和注册表

- [ ] **Step 1: 编写失败测试**

```python
def test_registry_rejects_duplicate_rule_versions(tmp_path):
    payload = [{
        "rule_id": "FIN-PAYMENT-TOTAL-001", "version": "1.0.0",
        "name": "付款比例合计检查", "category": "numeric",
        "agent": "finance", "dimensions": ["payment"],
        "contract_types": ["采购合同"], "severity": "high",
        "handler": "payment_total", "manual_review_on_unclear": True,
    }]
    (tmp_path / "finance.json").write_text(
        json.dumps(payload + payload, ensure_ascii=False), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="规则版本重复"):
        load_registry(tmp_path)

def test_registry_filters_by_agent_dimension_and_contract_type():
    registry = RuleRegistry([RuleDefinition(
        rule_id="FIN-PAYMENT-TOTAL-001", version="1.0.0",
        name="付款比例合计检查", category="numeric", agent="finance",
        dimensions=("payment",), contract_types=("采购合同",),
        severity="high", handler="payment_total",
    )])
    rules = registry.select(
        agent="finance", dimensions={"payment"}, contract_type="采购合同",
    )
    assert [rule.rule_id for rule in rules] == ["FIN-PAYMENT-TOTAL-001"]
```

- [ ] **Step 2: 实现严格 Schema**

```python
class RuleDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    rule_id: str
    version: str
    name: str
    category: Literal["completeness", "format", "numeric", "temporal", "cross_clause", "applicability", "escalation"]
    agent: Literal["legal", "finance", "system"]
    dimensions: tuple[str, ...]
    contract_types: tuple[str, ...] = ()
    severity: Literal["high", "medium", "low"]
    handler: str
    manual_review_on_unclear: bool = True
```

`RuleRegistry` 只允许预注册的 Handler 名称，JSON 中不能指定任意 Python 导入路径。

- [ ] **Step 3: 测试并提交**

Run: `a03-contract-audit/backend/.venv/Scripts/python.exe -m pytest a03-contract-audit/backend/tests/test_rule_registry.py -q`

Commit: `git commit -m "feat: add versioned audit rule registry"`

### Task 2: 实现统一规则执行器并迁移已有规则

- [ ] **Step 1: 添加命中、不命中、信息不足和异常测试**

```python
@pytest.mark.parametrize(("facts", "status"), [
    ({"payment_percentages": [30, 70]}, "not_hit"),
    ({"payment_percentages": [50, 60]}, "hit"),
    ({"payment_percentages": []}, "unclear"),
])
def test_payment_total_rule(facts, status):
    rule = RuleDefinition(
        rule_id="FIN-PAYMENT-TOTAL-001", version="1.0.0",
        name="付款比例合计检查", category="numeric", agent="finance",
        dimensions=("payment",), contract_types=("采购合同",),
        severity="high", handler="payment_total",
    )
    result = execute_rule(rule, facts)
    assert result.status == status
```

- [ ] **Step 2: 实现统一输出**

```python
class RuleResult(BaseModel):
    rule_id: str
    rule_version: str
    status: Literal["hit", "not_hit", "unclear", "error"]
    severity: Literal["high", "medium", "low"]
    clause_ids: list[str] = Field(default_factory=list)
    facts: dict[str, JsonValue] = Field(default_factory=dict)
    calculation: str = ""
    reason_code: str
```

Handler 发生异常时返回 `error` 和受控原因码，同时记录日志；异常文本不得写入面向用户的结果。

- [ ] **Step 3: 迁移确定性规则**

把主体缺失、工作范围缺失、付款方式缺失和人身损害绝对免责从 `deterministic_checks.py` 迁入定义文件及 Handler。兼容函数 `find_deterministic_findings()` 继续存在，并把 `RuleResult(status="hit")` 映射为旧 `DeterministicFinding`。

- [ ] **Step 4: 验证并提交**

Run: `a03-contract-audit/backend/.venv/Scripts/python.exe -m pytest a03-contract-audit/backend/tests/test_rule_executor.py a03-contract-audit/backend/tests/test_deterministic_audit_checks.py a03-contract-audit/backend/tests/test_contract_logic.py -q`

Commit: `git commit -m "refactor: execute deterministic checks through rule engine"`

### Task 3: 增加首批财务与跨条款规则

- [ ] **Step 1: 先写参数化边界测试**

覆盖付款比例 99.99/100/100.01、万元与元、大写金额、条件性付款不盲目求和、收款主体缺失/一致/不一致、签署与履行日期先后、同一触发条件的付款期限冲突。

- [ ] **Step 2: 实现 Handler**

数值计算统一使用 `Decimal`；主体比较只标准化空白、全半角和已确认的公司名称别名，不删除公司后缀，不靠名称相似就认定同一法人；缺少统一社会信用代码或授权代收关系时保留 `unclear`。日期只有在完整年月日均可解析时比较；条件性付款无法确定同一基数时返回 `unclear`。

- [ ] **Step 3: 记录计算轨迹**

```python
RuleResult(
    rule_id="FIN-PAYMENT-TOTAL-001", rule_version="1.0.0",
    status="hit", severity="high", clause_ids=["C-3", "C-4"],
    facts={"percentages": ["50", "60"], "total": "110"},
    calculation="50 + 60 = 110", reason_code="PAYMENT_TOTAL_EXCEEDS_100",
)
```

- [ ] **Step 4: 验证并提交**

Run: `a03-contract-audit/backend/.venv/Scripts/python.exe -m pytest a03-contract-audit/backend/tests/test_rule_executor.py a03-contract-audit/backend/tests/test_payment_insights.py a03-contract-audit/backend/tests/test_contract_logic.py -q`

Commit: `git commit -m "feat: add financial and cross-clause audit rules"`

### Task 4: 实现五层证据支持验证

- [ ] **Step 1: 写入每层门禁测试**

```python
def test_expired_source_cannot_be_supported():
    risk = {
        "category": "违约金过高", "original_text": "违约金为合同金额50%",
        "original_text_verified": True, "risk_reason": "违约金可能过高",
    }
    source = {
        "content": "约定违约金过分高于损失的，可以请求适当减少。",
        "source": "旧法条", "reliable": True, "applicability_status": "expired",
    }
    result = verify_support(risk, [source])
    assert result.status == "unclear"
    assert result.failed_stage == "applicability"

def test_contradicting_authorized_source_is_contradicted():
    risk = {
        "category": "法定书面形式缺失", "original_text": "双方仅口头约定",
        "original_text_verified": True, "risk_reason": "该合同必须采用书面形式",
    }
    source = {
        "content": "当事人订立合同，可以采用书面形式、口头形式或者其他形式。",
        "source": "授权法条", "reliable": True,
        "applicability_status": "applicable",
    }
    result = verify_support(
        risk, [source],
        semantic_verifier=lambda _risk, _sources: "contradicted",
    )
    assert result.status == "contradicted"
    assert result.failed_stage == "semantic_relation"
```

- [ ] **Step 2: 实现分层结果**

```python
class SupportValidation(BaseModel):
    status: Literal["supported", "unclear", "contradicted"]
    failed_stage: Literal["none", "original", "authority", "applicability", "facts", "semantic_relation"]
    reason_code: str
    reason: str
    version: str = "support-v3"
```

验证顺序固定为原文、权威性、适用性、事实一致性、语义关系。前一层失败后停止自动接受，但保留来源和失败轨迹。词面规则只能输出明确支持或 `unclear`；没有可靠矛盾识别证据时不得猜测 `contradicted`。

定义 `verify_support(risk: dict, sources: list[dict], *, semantic_verifier: Callable | None = None) -> SupportValidation`。语义判断必须来自系统注入的验证器，不能接受来源正文或来源字典中自报的 `semantic_relation`。上述 lambda 只验证决策传播，不代表真实矛盾识别能力；必须另用专家金标验证真实预测器后才允许启用。

- [ ] **Step 3: 保留旧函数兼容并替换调用点**

`validate_support_relation()` 继续接受风险字典和来源列表，内部转换到 V3；`auditor.py` 保存 `failed_stage` 与原因码，并保持现有状态字段。

- [ ] **Step 4: 验证并提交**

Run: `a03-contract-audit/backend/.venv/Scripts/python.exe -m pytest a03-contract-audit/backend/tests/test_evidence_support_validation.py a03-contract-audit/backend/tests/test_evidence_support_v3.py a03-contract-audit/backend/tests/test_rag_grounding.py -q`

Commit: `git commit -m "feat: validate evidence through layered support gates"`

### Task 5: 统一最终风险决策

- [ ] **Step 1: 编写决策表测试**

```python
@pytest.mark.parametrize(("original", "support", "conflict", "decision"), [
    (True, "supported", False, "accepted"),
    (False, "supported", False, "manual_review"),
    (True, "unclear", False, "manual_review"),
    (True, "contradicted", False, "rejected"),
    (True, "supported", True, "manual_review"),
])
def test_decide_risk(original, support, conflict, decision):
    assert decide_risk(
        original_verified=original,
        support_status=support,
        has_conflict=conflict,
    ).status == decision
```

- [ ] **Step 2: 实现纯决策函数**

```python
@dataclass(frozen=True)
class RiskDecision:
    status: Literal["accepted", "manual_review", "rejected"]
    reason_codes: tuple[str, ...]

def decide_risk(*, original_verified, support_status, has_conflict,
                rule_statuses=(), parse_quality_ok=True):
    reasons: list[str] = []
    if original_verified is not True:
        reasons.append("ORIGINAL_TEXT_UNRESOLVED")
    if not parse_quality_ok:
        reasons.append("PARSE_QUALITY_LOW")
    if has_conflict:
        reasons.append("UNRESOLVED_CONFLICT")
    if any(status in {"unclear", "error"} for status in rule_statuses):
        reasons.append("RULE_RESULT_UNRESOLVED")
    if reasons:
        return RiskDecision("manual_review", tuple(reasons))
    if support_status == "contradicted":
        return RiskDecision("rejected", ("EVIDENCE_CONTRADICTS_CLAIM",))
    if support_status != "supported":
        return RiskDecision("manual_review", ("EVIDENCE_UNRESOLVED",))
    return RiskDecision("accepted", ("ALL_GATES_PASSED",))
```

时点未知在支持关系层映射为 `support_status="unclear"`；规则 `hit` 是否改变风险等级由显式升级规则决定，不在此函数隐式推断。

- [ ] **Step 3: 替换分散状态赋值**

`auditor.py` 和 `secondary_review.py` 不再分别修改 `claim_status`、`requires_manual_review` 和 `tier`；统一根据 `RiskDecision` 映射，红档敏感类别规则作为显式升级规则执行。

- [ ] **Step 4: 验证并提交**

Run: `a03-contract-audit/backend/.venv/Scripts/python.exe -m pytest a03-contract-audit/backend/tests/test_risk_decision.py a03-contract-audit/backend/tests/test_secondary_review.py a03-contract-audit/backend/tests/test_audit_result_quality.py -q`

Commit: `git commit -m "refactor: centralize risk publication decisions"`

### Task 6: 持久化规则和决策轨迹

- [ ] **Step 1: 添加迁移测试**

为 `risks` 增加 `rule_executions_json`、`decision_trace_json`、`applicability_status` 和 `applicability_reason`；旧记录默认 `[]`、`{}`、`unknown` 和空字符串。测试升级、降级和旧行读取。

- [ ] **Step 2: 编写 Alembic 迁移和 ORM 字段**

字段使用 `Text` 保存受控 JSON，避免引入数据库专属类型；Pydantic Schema 使用与现有追踪数组相同的安全 JSON 解析器。

- [ ] **Step 3: 更新 Runner 原子写入**

风险、规则轨迹和决策轨迹在同一现有事务中写入；序列化失败使本次持久化失败并由任务恢复，不允许只保存最终状态而丢失依据。

- [ ] **Step 4: 验证并提交**

Run: `a03-contract-audit/backend/.venv/Scripts/python.exe -m pytest a03-contract-audit/backend/tests/test_db_migrations.py a03-contract-audit/backend/tests/test_rag_evidence_persistence.py a03-contract-audit/backend/tests/test_audit_runner_quality.py -q`

Commit: `git commit -m "feat: persist audit rule and decision traces"`

### Task 7: 本阶段验收

- [ ] Run: `a03-contract-audit/backend/.venv/Scripts/python.exe -m pytest a03-contract-audit/backend/tests/test_rule_registry.py a03-contract-audit/backend/tests/test_rule_executor.py a03-contract-audit/backend/tests/test_evidence_support_validation.py a03-contract-audit/backend/tests/test_evidence_support_v3.py a03-contract-audit/backend/tests/test_risk_decision.py a03-contract-audit/backend/tests/test_deterministic_audit_checks.py a03-contract-audit/backend/tests/test_contract_logic.py -q`
- [ ] Run: `git diff --check`
- [ ] Run: `powershell -NoProfile -ExecutionPolicy Bypass -File a03-contract-audit/scripts/quality_gate.ps1`
- [ ] Commit: `git commit -m "test: verify rule and evidence decision pipeline"`
