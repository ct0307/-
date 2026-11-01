# 合同审查批量优化启用协议

## 当前边界

批量开关 `AUDIT_BATCH_ENRICHMENT_ENABLED`、`AUDIT_BATCH_SECONDARY_ENABLED` 保持关闭。
本地模拟测试只能证明失败契约、隔离与串行/批量逻辑等价，不能证明真实模型准确率或速度达标。
不并行法务与财务 Agent，不扩大窗口，不跳过事实、原文、证据和二次复核校验。

## A/B 输入与执行

真实模型运行前须确认调用费用与合同数据外发授权。只使用获授权的冻结合同集及人工标注；
合同集覆盖高风险、无风险、缺页、扫描件、长合同和模型失败样本。不得只保留成功任务。
基线关闭两开关，候选开启两开关，除此之外模型、提示词、知识修订、维度、并发、整体时限均相同。
批量封装改变不应掩盖实质提示词变化；提示词指纹按同一规范生成并保留原始版本的内部索引。
冷缓存与热缓存分别执行，多轮交替运行，避免供应商抖动或缓存差异造成虚假提速。

每次运行生成脱敏 JSON（以下值仅说明格式，不是实测结果）：

```json
{
  "name": "baseline",
  "identity": {
    "dataset_sha256": "冻结合同集指纹",
    "model": "精确模型版本",
    "prompt_sha256": "提示词版本指纹",
    "knowledge_revision": 1,
    "dimensions": ["legal", "payment"],
    "concurrency": 2,
    "deadline_seconds": 1500
  },
  "quality_metrics": {
    "high_risk_recall": 0.95,
    "risk_f1": 0.90,
    "evidence_support_rate": 0.98,
    "coverage_rate": 1.0,
    "manual_review_rate": 0.20
  },
  "samples": [{
    "case_id": "脱敏稳定样本编号",
    "total_ms": 1000,
    "timings": {"parse_ms": 10, "legal_agent_ms": 500, "finance_agent_ms": 490},
    "llm_calls": [{"latency_ms": 100}],
    "parse_cache_hit": false,
    "fallback_count": 0,
    "risks": [{"level": "high", "evidence_status": "supported", "requires_manual_review": false}],
    "unauthorized_evidence_count": 0,
    "unverified_auto_publish_count": 0
  }]
}
```

`total_ms` 是单任务端到端耗时，不是模型调用耗时之和。计数与总耗时使用非负整数毫秒。
五项质量指标取值为 0 到 1，均由同一标注集、同一评测口径计算，不得手工填零冒充安全通过。
同时保存各样本终态、失败码、人工复核原因及批次墙钟耗时，独立核对失败率与吞吐。
不要将合同正文、模型响应、密钥、原始异常或本机路径写入发布报告。

从 `backend/` 执行（输入放在不提交的 `outputs/` 中）：

```powershell
.\.venv\Scripts\python.exe -m evaluation.cli audit-performance `
  --baseline ../outputs/audit-ab/baseline.json `
  --candidate ../outputs/audit-ab/candidate.json `
  --json-output ../outputs/audit-ab/comparison.json `
  --markdown-output ../outputs/audit-ab/comparison.md
```

## 质量与速度判定

| 优先级 | 条件 | 处置 |
|---|---|---|
| P1 | 候选越权证据或未核验自动发布非零 | 失败，禁止启用，即使其他资料缺失 |
| P1 | 必需身份、同样本编号、质量或安全指标缺失 | blocked，不得按零处理 |
| P1 | 完整资料下运行身份/样本集不一致或样本编号重复 | 失败，重做可比评测 |
| P1 | 高风险召回、风险 F1、证据支持、覆盖率任一下降 | 失败，禁止启用 |
| P2 | 人工复核比例上升 | 失败，人工核对后重新批准，不能直接开启 |
| P2 | 质量通过后总耗时 P50/P95、调用数、失败率与吞吐 | 联合评估，调用变少不等于实际更快 |

CLI 退出码：0 为质量门通过，4 为失败，5 为缺少验收资料；非法输入按 CLI 输入错误返回。
质量门通过只是启用必要条件，不是自动改配置的授权。速度没有改善、失败率升高或人工复核负担异常时不启用。
所有缺失指标在报告中明确列出。仅 samples 的 JSONL 缺少运行身份与业务质量，不能用于正式启用验收。

## 目标异步环境验收

在独立获授权的 PostgreSQL、Redis、Celery 测试环境验收既有并发 2，不能用当前 SQLite 本地线程池的结果替代。
检查多合同同时运行时的任务隔离、重复提交幂等、工作进程重启恢复、租约过期、重试筛选和批次进度恢复。
测量批次墙钟耗时、排队时间、失败率、吞吐以及总耗时 P50/P95，并保留版本与配置证据。
未经确认不迁移业务数据库、不调整生产并发、不部署。先小范围启用，出现质量回退立即关闭两开关，保留证据后分析。

## 本轮证据限制

本轮仅执行本地代码回归与页面测试。尚未执行真实公网模型 A/B、正式 52 文件集、PostgreSQL/Celery 吞吐或 OCR 准确率实测。
上述缺失验收完成前不得声称准确率达标或给出实际提速百分比。
