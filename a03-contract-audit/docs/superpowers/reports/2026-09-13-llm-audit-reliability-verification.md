# LLM 合同审查可靠性验证摘要

## 验证标识

| 项目 | 结果 |
|---|---|
| 本地验证时间 | 2026-09-14（UTC+08:00） |
| UTC 验证时间 | 2026-09-13 至 2026-09-14Z |
| 被验证 Git 提交 | `a0b218e`、`9cc394e`、`2e2aa82`、`8043496` |
| 验证前工作树 | clean |
| 验证后工作树 | clean（本摘要提交后） |

## 自动化验证

| 范围 | 命令摘要 | 退出码 | 实际结果 |
|---|---|---:|---|
| 后端目标回归 | 计划中的可靠性、二次复核、评测及边界测试 | 0 | 受影响回归 303 passed；最终后端 849 passed, 1 skipped |
| 前端目标回归 | `batch-store`、`audit-quality-state-e2e`、`audit-reliability-e2e` | 0 | 22 passed, 5 skipped |
| 前端类型检查 | `npm.cmd run type-check` | 0 | passed |
| 前端生产构建 | `npm.cmd run build` | 0 | 2360 modules transformed, build passed |
| 完整门禁：evaluation | `scripts/quality_gate.ps1` | 0 | 87 passed |
| 完整门禁：backend | `scripts/quality_gate.ps1` | 0 | 849 passed, 1 skipped, 6 warnings |
| 完整门禁：frontend | `scripts/quality_gate.ps1` | 0 | 71 passed, 26 skipped |
| 完整门禁：type-check | `scripts/quality_gate.ps1` | 0 | passed |
| 完整门禁：build | `scripts/quality_gate.ps1` | 0 | 2360 modules transformed, build passed |

测试输出未记录真实合同正文、prompt、模型响应正文或密钥。完整质量门禁总退出码为 0。

## 浏览器验证

- 环境：本地隔离 SQLite、合成数据。
- 视口：桌面 1440 x 900；移动端 375 x 812。
- 覆盖：空状态；`reviewing -> validating -> done` 状态迁移；刷新后恢复。
- 人工复核：`review_required` 显示原因、部分结果和 `job_id`，不显示重试操作。
- 失败处理：`failed` 显示重试操作；访问不存在的批次时清除旧结果并显示错误。
- 可靠性边界：旧 generation 不覆盖新结果；from-import 陈旧任务可恢复源项，已完成源项不会回退；非法覆盖率、维度或金额/日期事实进入人工复核。
- 界面质量：两个视口均无水平溢出，浏览器控制台无应用错误。

## A/B 与结论边界

```yaml
evaluation_input_sha256: not_applicable
public_model_ab:
  status: not_run
  reason: 未取得费用和数据外发的明确授权
selected: null
```

本次已实现并验证首选的选择性级联架构。代码质量复审无 P1/P2；由于真实公网模型 A/B 未运行，未产生通过全部 P1/P2 质量门槛且成本字段完整的候选，因此不能称为“最具性价比”。

以下范围未验证，不得外推为达标：真实 52 文件、PostgreSQL、OCR 准确率、OpenClaw/GPU 和能耗实测。
