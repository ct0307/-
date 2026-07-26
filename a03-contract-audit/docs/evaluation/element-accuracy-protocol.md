# 合同要素准确率评测协议

## 评测对象

评测只接受经过人工复核并冻结版本的 JSONL 金标准。每条记录必须包含 `case_id`、文件名、合同类型、文档类型、审核人、版本及六个核心要素；扫描 PDF 必须标记为 `scanned_pdf`。

金标准结构以 `backend/evaluation/schema.json` 为准。预测文件每行包含 `case_id` 和 `prediction` 对象，字段名与 `gold` 一致。

## 指标口径

- 甲方、乙方、标的、金额、期限按规范化后的完全匹配计算；只折叠 Unicode 兼容形式和空白，不做可能改变语义的模糊匹配。
- 付款节点按集合计算 Precision、Recall、F1。
- 总体结果采用六个字段的宏平均，防止高频字段掩盖低质量字段。
- 金标准与预测同时为空才视为正确；金标准非空但预测为空计漏报，金标准为空但预测非空计误报。
- JSON 报告保留总体、字段、合同类型、文档类型、错误案例和逐案例结果；CSV 保留逐案例逐字段原始指标。

## 复现命令

```powershell
python -m evaluation.cli --gold data/gold.jsonl --predictions data/predictions.jsonl --output-json results/elements.json --output-csv results/elements.csv
```

报告中的 `dataset_sha256` 绑定本次金标准内容。未提供人工标注集时，不得填写或展示准确率结论。
