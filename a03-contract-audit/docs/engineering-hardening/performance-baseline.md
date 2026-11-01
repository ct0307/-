# 离线性能基线与人工金标验收

本轮补齐既有 `evaluation.cli audit-performance` 入口，无需新装依赖。它只读取显式提供的脱敏 JSON/JSONL，不连接模型、数据库或应用服务，不加载应用配置。没有执行真实合同、真实模型、52 文件、OCR、PostgreSQL、OpenClaw/GPU 或能耗验收；本说明不包含实测质量分数。

## 选择正确入口

| 优先级 | 入口 | 用途与限制 |
|---|---|---|
| P1 | `audit-performance` | 离线比较既有审查运行摘要；提供总耗时、阶段均值/P50/P95、调用数/延迟、输入样本自动成功率及质量门禁缺项 |
| P2 | `benchmark` | 既有独立模型调用基准，含 3 轮预热与 5 轮测量；运行会调用目标服务，本次不执行。不能据此称解析、审查、落库全链路达标 |
| P1 | `audit-quality` / `audit-compare` | 在人工金标和预测文件齐备后评测；本次不伪造金标或用模型自评分替代人工质量分数 |

## 输入约定

JSON 使用 `{"name":"baseline","samples":[...]}`；JSONL 每行一个样本对象。保留原有 `case_id` 脱敏标识，按一次审查任务一个样本组织；同一合同多次试验时使用独立运行文件，不将多次尝试误作独立合同。

下面仅用于验证格式，为合成数据，不是性能实测：

```json
{
  "name": "synthetic-baseline",
  "samples": [
    {
      "case_id": "synthetic-001",
      "status": "done",
      "total_ms": 1200,
      "timings": {
        "parse_ms": 100,
        "legal_agent_ms": 700,
        "finance_agent_ms": 600,
        "grounding_ms": 40,
        "persist_ms": 20
      },
      "llm_calls": [{"latency_ms": 600}, {"latency_ms": 500}],
      "parse_cache_hit": false,
      "fallback_count": null
    }
  ]
}
```

- 兼容 `runner.py` 的 `audit.performance` 事件：`parse_ms`、`legal_agent_ms`、`finance_agent_ms`、`grounding_ms`、`persist_ms` 可放在样本顶层；同时存在时以 `timings` 内字段为准。
- 调用数来自完整 `llm_calls` 数组；空数组表示确认没有调用，缺字段或 `null` 表示未知。可由既有 `LLMCallLog.latency_ms` 脱敏导出后构造，每次尝试均保留，不能只保留成功调用。不得仅凭 `contract_id` 合并不同审查任务；使用 `audit_job_id` 等可靠任务关联，没有可靠关联时保留未知。本工具不自行查询或导出数据库。
- 不传合同正文、提示词、模型原文、真实文件名、用户信息、密钥或令牌。报告只输出白名单统计字段，不回显样本内容；运行名称也必须是脱敏别名。
- 计数与 `total_ms` 必须为非负整数；调用及阶段延迟必须为非负有限数值。已知真实零值可以填写 `0`，未采集或无法核实的数据填写 `null` 或省略。
- 阶段字段限制为上述五项，避免将任意日志内容变成报告字段。

## 执行命令

从正式项目根目录运行，输入文件必须事先完成脱敏。输出建议放在不提交的 `outputs/` 中。下面两个输出路径应选择新的文件名，避免覆盖要保留的报告：

```powershell
Push-Location backend
.\.venv\Scripts\python.exe -m evaluation.cli audit-performance `
  --baseline ..\outputs\baseline.json `
  --candidate ..\outputs\candidate.json `
  --json-output ..\outputs\performance-comparison.json `
  --markdown-output ..\outputs\performance-comparison.md
$resultCode = $LASTEXITCODE
Pop-Location
$resultCode
```

只有一份基线时，可将 `--baseline` 与 `--candidate` 指向同一文件以生成汇总，差值只表示同一输入的自比较，不能证明优化效果。

| 退出码 | 含义 |
|---|---|
| `0` | 既有质量比较门禁通过；性能是否满足业务阈值需另核验 |
| `2` | 输入错误，包括非法数值或文件问题 |
| `3` | 未预期执行异常 |
| `4` | 质量门禁失败 |
| `5` | 质量/身份/必需比较数据不足；JSON 与 Markdown 仍已生成，可作为性能观测摘要 |

只提供性能摘要时，通常应得到 `5`，不是质量通过。原有质量门禁要求基线和候选有一致的运行身份、样本集合、人工质量指标和安全计数；详见既有 `compare_runs`。新增性能观测缺项列入 `unavailable_metrics`，不改变原有质量门禁判断条件。

## 统计口径与证据边界

| 指标 | 口径 |
|---|---|
| 自动成功率 | 输入样本中 `done / 全部样本`；`review_required` 单列；`audit_failed`、`failed` 为失败。任一样本缺状态或未终结时返回 `null` |
| 总耗时与分位数 | 全部输入样本的 `total_ms`；包含有记录的失败任务，任一缺失则不输出偏向完整样本的统计 |
| 阶段统计 | 五个阶段逐项输出有效样本数/全部样本数；有缺失时均值/P50/P95 为 `null`，Markdown 显示“不可用” |
| LLM 分位数 | 所有调用的延迟；调用列表或任一延迟缺失时不输出完整口径的分位数；已确认零调用的分位数仍为 `null` |
| P50/P95 算法 | 排序后按位置 `(n-1)×p` 线性插值，保留三位小数；单样本分位数等于该样本值，不代表稳定尾延迟 |
| 阶段与总耗时关系 | Agent 可能并行，grounding 可能包含在 Agent 阶段内；不累加阶段估算总耗时 |

当前 `audit.performance` 日志在发布/落库后记录，异常路径未必生成同类记录。若只导出这些日志，自动成功率的分母只覆盖已记录任务，不能称全任务成功率。完整任务台账须补齐失败、超时、取消和未知结果，且不能以日志缺失推断成功或耗时零值。调用日志遗漏失败尝试时同样不能声称总调用数完整。

比较前固定数据集哈希、模型、提示词哈希、知识库修订、维度、并发和截止时间；记录环境、代码版本、冷/热缓存、样本数量和预热规则。首审、重审、单 Agent 实验应分别标注，独立首审实验不能称全链路。不同样本数的总耗时差值也不能直接解释为速度提升。

## 小规模人工金标规范（待执行）

先进行 12—20 份经授权、脱敏的试评，覆盖至少两类合同、明确高风险、普通条款、无风险负样本、证据不足与应人工复核情况。该规模用于校准标注规则，不能替代正式冻结数据集验收。

1. 标注负责人先冻结样本清单、`case_id`、数据哈希、风险分类和标注指南；预测结果不得提前暴露给独立标注者。
2. 两名具有相应法务/财务能力的人员独立标注风险条款定位、风险类型/级别、支持证据、适用性、应否人工复核及理由。正文和证据内容留在授权环境，提交仓库的记录仅含脱敏标识和计数。
3. 分歧由第三名负责人裁决，保留原始双人标注与裁决理由。无法判定的项目标为未知，统计数量，不计作正确或无风险。
4. 冻结金标版本、哈希和评分匹配规则后，再运行既有质量评测入口。风险匹配按同一条款定位及风险类别判定，同一风险的重复预测计误报。
5. 分别报告高风险召回率、风险精确率/召回率/F1、证据支持率、维度覆盖率、人工复核率，并附 TP/FP/FN 与分母；零分母指标标不可用。高风险漏检、无证据自动发布与越权证据逐项复核。
6. 验收阈值在看预测结果前冻结并签字。沿用既有质量门禁时不得降低基线质量或增加未批准的人工复核负担；人工金标未完成时，结论保持“质量未验收”。

建议脱敏标注台账字段：`case_id`、`clause_id`、`risk_type`、`level`、`evidence_supported`、`applicability`、`requires_manual_review`、`annotator_id`、`adjudication_status`、`gold_version`。这些是标注流程字段，实际送入既有 `audit-quality` 的文件需按其现有模式组织，不将本台账直接冒充工具输入。

## 本轮验证

```powershell
Push-Location backend
.\.venv\Scripts\python.exe -m pytest tests/test_audit_performance_baseline.py tests/test_audit_performance.py tests/test_evaluation_cli.py tests/test_benchmark_stats.py tests/test_benchmark_runner.py -q
Pop-Location
```

新增测试覆盖先红后绿、缺失与 `null`、非法延迟、阶段分位数、终态成功率、人工复核单列、现有 CLI 生成报告、禁止网络连接和输出不含测试敏感文本。上述测试均使用合成数据；测试通过不代表真实运行性能或质量达标。
