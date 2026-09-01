# 合同要素准确率评测协议

## 评测对象

评测只接受经过双人复核并冻结版本的 JSONL 金标准。每条记录必须包含 `case_id`、文件名、合同类型、文档类型、两个唯一审核人、复核状态、版本及六个核心要素；扫描 PDF 必须标记为 `scanned_pdf`。

金标准结构以 `backend/evaluation/schema.json` 为准，CLI 使用 JSON Schema Draft 2020-12 逐行强制校验。`reviewers` 必须包含两个不重复的非空审核人标识；`review_status` 只能为 `agreed` 或 `adjudicated`，后者必须提供 `adjudicator`。审核人应使用内部编号或化名，避免个人信息进入证据。

预测文件每行包含 `case_id` 和 `prediction` 对象，字段名与 `gold` 一致。重复或未知预测 `case_id` 会使本次运行无效；缺失预测保留在分母中并按漏报计分。

## 指标口径

- 甲方、乙方、标的、金额、期限按规范化后的完全匹配计算；只折叠 Unicode 兼容形式和空白，不做可能改变语义的模糊匹配。
- 付款节点按集合计算 Precision、Recall、F1。
- 总体结果采用六个字段的宏平均，防止高频字段掩盖低质量字段。
- 金标准与预测同时为空才视为正确；金标准非空但预测为空计漏报，金标准为空但预测非空计误报。
- 原始 JSONL 证据保留总体、字段、合同类型、文档类型、错误字段和逐案例指标，但不保存甲乙方、金额、付款节点等原始字段值。
- 每次运行绑定金标准、预测文件、Schema、Git 提交和运行环境，原始事件只追加、不覆盖。

## 复现命令

```powershell
python -m evaluation.cli elements --gold data/gold.jsonl --predictions data/predictions.jsonl --runs-root evaluation-runs --run-id elements-20260901 --min-f1 0.90
python -m evaluation.cli report --run-dir evaluation-runs/elements-20260901
```

`manifest.json` 中的 `gold_sha256`、`predictions_sha256` 和 `schema_sha256` 绑定本次输入。未提供双人复核冻结金标准或真实预测结果时，不得填写或展示准确率达标结论；自动化测试通过只证明评测工具按约定工作。
