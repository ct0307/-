# 风险依据支持关系评测协议

## 评测对象

本协议评测“候选依据是否支持具体风险结论”，不评测法规来源本身是否权威，也不以模型置信度替代支持关系判断。每条风险通过同一 `case_id` 下唯一且稳定的 `risk_key` 与预测结果对应。

当前确定性校验器版本为 `rules-v2`。它只在可信来源命中有效风险类别锚点且存在足够语义重合时输出 `supported`，其余情况保守输出 `unclear`。`contradicted` 已纳入金标和评测口径，但当前规则不会自动推断该状态；在引入经验证的矛盾识别能力前，应由人工标注或其他受控预测器提供。

## 状态定义

| 状态 | 判定标准 | 处置要求 |
|---|---|---|
| `supported` | 依据内容直接支撑风险结论，关键主体、行为、条件和法律后果不存在实质冲突 | 可与原文核验、来源可信结果共同参与自动采信 |
| `unclear` | 依据不足、仅有通用词重合、缺失类风险无法由正向法条证明，或上下文不足以判断 | 必须人工复核，不得按已支持展示 |
| `contradicted` | 依据明确否定风险结论，或关键事实、适用条件、法律后果与结论相反 | 必须阻断自动采信并人工处理 |

数据库中的 `support_validator_version=unvalidated` 表示该记录未实际执行支持关系校验，不得解释为某个规则版本的结果。

## 金标治理

1. 两名审核人使用内部编号或化名，依据合同原文与可追溯来源独立标注，不先查看系统预测。
2. 两人一致时将 `review_status` 设为 `agreed`；存在分歧时由第三人裁决，设为 `adjudicated` 并填写 `adjudicator`。
3. 冻结后不得原位覆盖。规则、标注或样本变化必须提升 `version` 并保留旧版文件及哈希。
4. 合同原件、金标和预测文件按企业数据分级控制访问；评测运行目录只记录哈希、指标和案例标识，不写入合同正文或风险原文。
5. `risk_key` 在同一案例内必须唯一。新增、删除或拆分风险时必须同步提升数据集版本，禁止复用旧键表达不同风险。

金标结构以 `backend/evaluation/schema.json` 为准。下例为便于阅读而换行，实际 JSONL 每行只能包含一个完整 JSON 对象：

```json
{
  "case_id": "procurement-001",
  "file": "procurement-001.pdf",
  "contract_type": "采购合同",
  "document_kind": "pdf",
  "reviewers": ["reviewer-a", "reviewer-b"],
  "review_status": "agreed",
  "version": "v1",
  "gold": {
    "party_a": "甲公司",
    "party_b": "乙公司",
    "subject": "设备采购",
    "amount": "100万元",
    "duration": "12个月",
    "payment_terms": ["首付款"]
  },
  "evidence": [
    {"risk_key": "penalty-too-high", "support_relation_status": "supported"},
    {"risk_key": "missing-confidentiality", "support_relation_status": "unclear"}
  ]
}
```

预测文件同样采用 JSONL，每行包含 `case_id` 和 `prediction`：

```json
{"case_id":"procurement-001","prediction":{"evidence":[{"risk_key":"penalty-too-high","support_relation_status":"supported"},{"risk_key":"missing-confidentiality","support_relation_status":"unclear"}]}}
```

## 指标口径

- 总体指标为 `supported`、`unclear`、`contradicted` 三类 Precision、Recall、F1 的宏平均，避免多数类掩盖少数类表现。
- 同时报告准确率、正确数、风险总数和缺失预测数；缺失预测保留在分母中并按错误计入。
- 未知 `case_id`、未知 `risk_key`、重复键或非法状态会使本次运行无效，不能静默忽略。
- 阈值由业务负责人、法务和评测负责人共同批准；CLI 默认 `--min-f1 0.90` 只是技术默认值，不等同于企业验收结论。

## 复现命令

在 `backend/` 目录执行：

```powershell
.\.venv\Scripts\python.exe -m evaluation.cli evidence --gold data/evidence-gold.jsonl --predictions data/evidence-predictions.jsonl --runs-root evaluation-runs --run-id evidence-20260911 --min-f1 0.90
.\.venv\Scripts\python.exe -m evaluation.cli report --run-dir evaluation-runs/evidence-20260911
```

运行目录应包含 `manifest.json`、`evidence.jsonl` 和 `report.md`。`manifest.json` 使用 `gold_sha256`、`predictions_sha256`、`schema_sha256`、Git 提交和运行环境绑定输入；`evidence.jsonl` 保存逐案例与汇总指标事件。

## 证据边界

单元测试、测试夹具或合成样本通过，只能证明校验器和评测工具按约定工作，不能证明真实合同上的准确率、Macro F1 或业务可用性达标。只有使用经过双人复核、版本冻结、可追溯的脱敏真实合同金标，并保留完整运行产物后，才可以报告对应数据集与版本上的实测指标。
