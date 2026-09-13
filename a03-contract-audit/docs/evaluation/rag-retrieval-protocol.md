# RAG 检索金标评测协议

## 目标

用人工复核的查询-依据金标测量 Recall@K、Precision@K、MRR 和 nDCG@K。单元测试通过只证明评测器可用，不代表项目已经达到比赛阈值。

## 输入

金标准 JSONL 每行一个查询案例；`relevant_ids` 使用稳定的法条或知识切片 ID，不保存合同正文：

```json
{"case_id":"payment-001","relevant_ids":["LAW-585","RULE-PAYMENT-03"]}
```

预测 JSONL 保存系统返回的有序 ID：

```json
{"case_id":"payment-001","ranked_ids":["LAW-585","LAW-577","RULE-PAYMENT-03"]}
```

要求：

- `case_id` 唯一，金标准至少包含一个相关 ID。
- 同一案例的 ID 不得重复。
- 缺失预测按零分计入，不能只提交成功案例。
- 金标准至少覆盖精确条号、同义表达、跨条款、表格字段、OCR 错字、相似难负样本和缺失条款。

## 执行

在 `backend/` 目录运行：

```powershell
.\.venv\Scripts\python.exe -m evaluation.cli retrieval `
  --gold data/retrieval-gold.jsonl `
  --predictions data/retrieval-predictions.jsonl `
  --runs-root evaluation-runs `
  --run-id retrieval-20260913 `
  --k 5 `
  --min-recall 0.90

.\.venv\Scripts\python.exe -m evaluation.cli report `
  --run-dir evaluation-runs/retrieval-20260913
```

退出码 `0` 表示 Recall@K 达到传入阈值，`4` 表示未达到，`2` 表示输入无效。证据目录只保存哈希、案例 ID、计数和指标，不保存查询或合同正文。

## 消融对比

比赛报告至少保留四组同一金标结果：BM25、向量、BM25+向量 RRF、RRF+真实 Cross-Encoder。当前未配置 Cross-Encoder 时，系统保留融合顺序并将覆盖度评分标记为 `deterministic_evidence_v1`，不得写成模型 reranker。
