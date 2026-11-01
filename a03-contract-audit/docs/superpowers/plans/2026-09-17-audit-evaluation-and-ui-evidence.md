# 审查评测与前端证据展示 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用同一冻结上下文完成 V0-V4 消融对比，并以向后兼容的 API 在现有页面展示检索、规则、适用性和 Agent 协作证据。

**Architecture:** 评测工具从脱敏 JSONL 重算指标并强制比较上下文一致；API 只增加可选审计字段；前端仅扩展风险抽屉、协同页和报告证据抽屉。

**Tech Stack:** Python 3.11、pytest、Vue 3、TypeScript、Element Plus、Vitest/Playwright、Vite。

---

## 执行约定

以下命令从仓库外层目录执行，运行 pytest 前设置 `$env:PYTHONPATH=(Resolve-Path 'a03-contract-audit/backend').Path`。只暂存当前任务 Files 清单中的本轮修改，不使用 `git add .`。前端测试使用项目已有 Playwright runner；不能使用不存在的 Vitest 命令。

V0-V4 必须冻结合同金标、模型、温度、知识库、数据集和运行环境；允许且必须分别记录每个阶段的 `prompt_version`、`rule_version`、`reranker_version` 和 `support_validator_version`，因为这些正是消融自变量。

## 文件结构

- Create: `backend/evaluation/audit_ablation.py`。
- Modify: `backend/evaluation/cli.py` 和 `backend/evaluation/report.py`。
- Create: `backend/tests/test_audit_ablation.py`。
- Modify: `backend/tests/test_evaluation_cli.py` 和 `backend/tests/test_evaluation_report.py`。
- Modify: `backend/app/schemas/contract.py`。
- Modify: `frontend/src/api/types.ts`。
- Modify: `frontend/src/components/audit/RiskReviewDrawer.vue`。
- Modify: `frontend/src/views/CollaborationView.vue` 和 `frontend/src/views/ReportsView.vue`。
- Create: `frontend/src/utils/audit-trace.ts`。
- Create: `frontend/tests/risk-evidence-trace-e2e.spec.ts`。
- Create: `docs/evaluation/evidence-driven-audit-ablation-protocol.md`。

### Task 1: 建立 V0-V4 消融契约

- [ ] **Step 1: 编写冻结上下文失败测试**

```python
def test_ablation_rejects_different_models_or_gold_hashes():
    runs = [
        {
            "version": f"V{index}",
            "frozen_context": {
                "model_version": "model-1", "knowledge_base_version": "kb-1",
                "dataset_version": "gold-1", "temperature": 0,
                "environment": "local",
            },
            "component_versions": {
                "prompt_version": f"prompt-v{index}", "rule_version": f"rules-v{index}",
                "reranker_version": "disabled", "support_validator_version": "rules-v2",
            },
            "input_hashes": {"gold_sha256": "a" * 64},
            "overall": {"risk_precision": 0.8, "risk_recall": 0.8},
        }
        for index in range(5)
    ]
    runs[3]["frozen_context"]["model_version"] = "different"
    with pytest.raises(ValueError, match="冻结上下文"):
        compare_ablation_runs(runs)

def test_ablation_requires_exact_v0_to_v4_set():
    runs = [
        {"version": f"V{index}", "frozen_context": {},
         "input_hashes": {"gold_sha256": "a" * 64}, "overall": {}}
        for index in range(4)
    ]
    with pytest.raises(ValueError, match="V0-V4"):
        compare_ablation_runs(runs)
```

- [ ] **Step 2: 实现严格比较器**

```python
ABLATION_SCOPES = {
    "V0": "baseline",
    "V1": "independent_agents_prompts",
    "V2": "rules",
    "V3": "reranker",
    "V4": "support_v3",
}

def compare_ablation_runs(runs):
    by_version = {run["version"]: run for run in runs}
    if len(runs) != 5 or set(by_version) != set(ABLATION_SCOPES):
        raise ValueError("消融评测必须包含完整 V0-V4")
    ordered = [by_version[f"V{index}"] for index in range(5)]
    contexts = [run["frozen_context"] for run in ordered]
    gold_hashes = [run["input_hashes"]["gold_sha256"] for run in ordered]
    if any(context != contexts[0] for context in contexts[1:]) or len(set(gold_hashes)) != 1:
        raise ValueError("V0-V4 必须使用同一冻结上下文和金标准")
    metrics = (
        "risk_precision", "risk_recall", "risk_f1", "high_risk_recall",
        "unsupported_claim_rate", "false_accept_rate", "manual_review_rate",
        "unique_contribution_rate", "claim_correction_rate", "conflict_rate",
        "p50_latency_ms", "p95_latency_ms", "mean_tokens", "success_rate",
    )
    rows = []
    for index, run in enumerate(ordered):
        previous = ordered[index - 1]["overall"] if index else None
        baseline = ordered[0]["overall"]
        rows.append({
            "version": run["version"],
            "scope": ABLATION_SCOPES[run["version"]],
            "overall": run["overall"],
            "component_versions": run["component_versions"],
            "delta_previous": {
                metric: None if previous is None else run["overall"].get(metric) - previous.get(metric)
                for metric in metrics
                if run["overall"].get(metric) is not None
                and (previous is None or previous.get(metric) is not None)
            },
            "delta_v0": {
                metric: run["overall"].get(metric) - baseline.get(metric)
                for metric in metrics
                if run["overall"].get(metric) is not None and baseline.get(metric) is not None
            },
        })
    return {"gold_sha256": gold_hashes[0], "runs": rows}
```

在相减前校验每个指标是有限数值或 `None`，拒绝布尔值、NaN 和无穷值；`not_measured` 只作为报告文案，JSON 用 `null` 保存。复用现有冻结字段时明确排除 `prompt_version`，组件版本单独记录；模型、温度、数据集、知识库和环境保持固定。

- [ ] **Step 3: 增加指标**

比较结果至少包含风险 Precision/Recall/F1、高风险 Recall、Unsupported Claim Rate、错误自动接受率、人工复核率、Unique Contribution Rate、Claim Correction Rate、冲突率、P50/P95、Token 和成功率。缺少指标时标记 `not_measured`，不填零。

- [ ] **Step 4: 测试并提交**

Run: `a03-contract-audit/backend/.venv/Scripts/python.exe -m pytest a03-contract-audit/backend/tests/test_audit_ablation.py -q`

Commit: `git commit -m "feat: add frozen V0-V4 audit ablation comparison"`

### Task 2: 接入 CLI、报告和评测协议

- [ ] **Step 1: 添加 CLI 失败测试**

```python
def test_audit_ablation_cli_writes_manifest_events_and_report(tmp_path):
    arguments = ["audit-ablation"]
    for index in range(5):
        path = tmp_path / f"v{index}.json"
        path.write_text(json.dumps({
            "version": f"V{index}",
            "frozen_context": {
                "model_version": "model-1", "knowledge_base_version": "kb-1",
                "dataset_version": "gold-1", "temperature": 0, "environment": "local",
            },
            "component_versions": {
                "prompt_version": f"prompt-v{index}", "rule_version": "rules-1",
                "reranker_version": "disabled", "support_validator_version": "rules-v2",
            },
            "input_hashes": {"gold_sha256": "a" * 64},
            "overall": {"risk_precision": 0.8, "risk_recall": 0.8},
        }), encoding="utf-8")
        arguments.extend(["--run", str(path)])
    code = main(arguments + [
        "--runs-root", str(tmp_path), "--run-id", "ablation-1",
    ])
    assert code == 0
    assert (tmp_path / "ablation-1" / "manifest.json").exists()
    assert (tmp_path / "ablation-1" / "evidence.jsonl").exists()
    assert (tmp_path / "ablation-1" / "report.md").exists()
```

- [ ] **Step 2: 增加 `audit-ablation` 子命令**

参数使用五个可重复 `--run`，输出复用现有评测快照规范。Manifest 保存输入 SHA-256、Git 提交和工具版本，不保存合同正文。

- [ ] **Step 3: 编写评测协议**

协议明确开发/验证/盲测拆分、双人标注与仲裁、V0-V4 唯一变更范围、模型下载与外发授权、合成数据证据边界以及失败退出码。

- [ ] **Step 4: 验证并提交**

Run: `a03-contract-audit/backend/.venv/Scripts/python.exe -m pytest a03-contract-audit/backend/tests/test_audit_ablation.py a03-contract-audit/backend/tests/test_evaluation_cli.py a03-contract-audit/backend/tests/test_evaluation_report.py -q`

Commit: `git commit -m "feat: report evidence-driven audit ablations"`

### Task 3: 扩展向后兼容 API 类型

- [ ] **Step 1: 添加 Schema 测试**

```python
def test_risk_out_defaults_new_trace_fields_for_old_rows():
    risk = RiskOut.model_validate({
        "id": 1, "agent": "legal", "level": "medium", "category": "付款风险",
        "original_text": "验收后付款", "basis": "待核验", "suggestion": "明确期限",
        "confidence": 0, "tier": "yellow", "review_status": "pending",
    })
    assert risk.applicability_status == "unknown"
    assert risk.rule_executions == []
    assert risk.decision_trace == {}
    assert risk.collaboration_trace is None
```

- [ ] **Step 2: 增加可选响应字段**

```python
class CollaborationTraceOut(BaseModel):
    discovered_by: str
    reviewed_by: list[str] = Field(default_factory=list)
    corrected: bool = False
    conflict: bool = False

class RiskOut(BaseModel):
    # 保留原字段
    applicability_status: str = "unknown"
    applicability_reason: str = ""
    rule_executions: list[dict] = Field(default_factory=list)
    decision_trace: dict = Field(default_factory=dict)
    collaboration_trace: CollaborationTraceOut | None = None
```

- [ ] **Step 3: 验证旧记录和接口**

Run: `a03-contract-audit/backend/.venv/Scripts/python.exe -m pytest a03-contract-audit/backend/tests/test_contract_quality_api.py a03-contract-audit/backend/tests/test_rag_evidence_persistence.py a03-contract-audit/backend/tests/test_report_scope.py -q`

Commit: `git commit -m "feat: expose optional audit decision traces"`

### Task 4: 增加前端类型和安全格式化器

- [ ] **Step 1: 添加工具测试**

测试未知状态、缺失数组、超长规则输入、降级精排和旧 API。所有未知值显示“待核验”，不能显示为通过。

```typescript
import { test, expect } from '@playwright/test'
import { applicabilityMeta } from '../src/utils/audit-trace'

test('未知适用性不能显示通过', () => {
  expect(applicabilityMeta(undefined)).toEqual({ label: '待核验', type: 'warning' })
  expect(applicabilityMeta('unexpected').type).not.toBe('success')
})
```

- [ ] **Step 2: 扩展 `RiskOut`**

```typescript
export interface AuditRuleExecution {
  rule_id: string
  rule_version: string
  status: 'hit' | 'not_hit' | 'unclear' | 'error' | string
  calculation?: string
  reason_code: string
}

export interface CollaborationTrace {
  discovered_by: 'legal' | 'finance' | 'system'
  reviewed_by: Array<'legal' | 'finance'>
  corrected: boolean
  conflict: boolean
}
```

新增字段全部使用 `?`，旧接口响应仍可渲染。

- [ ] **Step 3: 实现格式化器**

`audit-trace.ts` 将适用性、规则状态、精排模式和协作状态映射成中文文案与 Element Plus 状态类型；未知、缺失和错误统一使用 warning/danger，不使用 success。

```typescript
export function applicabilityMeta(status?: string): {
  label: string
  type: 'success' | 'warning' | 'danger'
} {
  if (status === 'applicable') return { label: '适用性已核验', type: 'success' }
  if (status === 'expired' || status === 'not_yet_effective') {
    return { label: '法规时点不适用', type: 'danger' }
  }
  return { label: '待核验', type: 'warning' }
}
```

- [ ] **Step 4: 验证并提交**

Run: `npm.cmd --prefix a03-contract-audit/frontend run test -- risk-evidence-trace-e2e.spec.ts`

Commit: `git commit -m "feat: type and format audit evidence traces"`

### Task 5: 扩展风险复核抽屉

- [ ] **Step 1: 编写 Playwright 失败用例**

覆盖完整证据、旧 API 缺字段、无来源、精排降级、规则冲突和 390px 视口。断言不存在横向滚动，未知适用性显示“待核验”，冲突要求人工复核。

- [ ] **Step 2: 修改现有抽屉，不创建新页面**

在 `RiskReviewDrawer.vue` 的“法规/规则依据”后增加三个非嵌套区块：

1. 法规适用：状态、时点和原因；
2. 规则核验：规则名称/ID、版本、状态和计算过程；
3. Agent 协作：发现者、复核者、纠正和冲突。

检索来源卡增加召回方式和精排模式，但不向普通用户展示原始模型分数。空数组使用现有空证据样式，不渲染空卡片。

- [ ] **Step 3: 前端验证并提交**

Run: `npm.cmd --prefix a03-contract-audit/frontend run test -- risk-evidence-trace-e2e.spec.ts`

Run: `npm.cmd --prefix a03-contract-audit/frontend run type-check`

Expected: PASS。

Commit: `git commit -m "feat: show risk evidence and decision traces"`

### Task 6: 协同页和报告最小联动

- [ ] **Step 1: 增加组件测试**

测试独立贡献、被纠正、未解决冲突、没有协作轨迹和导出范围不变。

- [ ] **Step 2: 修改现有视图**

`CollaborationView.vue` 在风险行内增加短状态，不新增装饰性 Agent 动画；`ReportsView.vue` 的证据抽屉复用格式化器展示适用性和规则摘要。后端未返回新字段时保持当前页面结构和文案。

- [ ] **Step 3: 构建与提交**

Run: `npm.cmd --prefix a03-contract-audit/frontend run test`

Run: `npm.cmd --prefix a03-contract-audit/frontend run type-check`

Run: `npm.cmd --prefix a03-contract-audit/frontend run build`

Commit: `git commit -m "feat: surface agent collaboration evidence"`

### Task 7: 浏览器和项目级验收

- [ ] 启动后端：`a03-contract-audit/backend/.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000`。
- [ ] 启动前端：`npm.cmd --prefix a03-contract-audit/frontend run dev -- --host 127.0.0.1 --port 5173`。
- [ ] 使用浏览器验证完整证据、旧记录、空状态、错误/降级、Agent 冲突和人工复核动作。
- [ ] 在 1440x900、1024x768 和 390x844 检查遮挡、溢出、换行和抽屉滚动。
- [ ] Run: `powershell -NoProfile -ExecutionPolicy Bypass -File a03-contract-audit/scripts/quality_gate.ps1`
- [ ] Run: `git diff --check`
- [ ] 更新 `docs/evaluation/hard-indicator-matrix.md`，只填写本轮真实执行证据；没有专家金标或真实精排模型时保持“待实测”。
- [ ] Commit: `git commit -m "test: verify evidence-driven audit experience"`
