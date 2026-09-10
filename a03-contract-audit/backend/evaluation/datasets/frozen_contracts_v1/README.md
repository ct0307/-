# 高拟真合成冻结合同集 v1

本目录保存生成器、案例事实和校验规则；生成后的二进制合同位于项目根目录下被 Git 忽略的 `outputs/frozen-contracts-v1/`。

> **专业复核状态：未批准作为企业级高拟真基准。** v1 可作为技术预检基线，但已确认存在“冲突案例未落入实际冲突值”“法务修订稿无真实修订结构”和“风险条款过度合规化”等缺口。详见 `docs/evaluation/frozen-contracts-v1-professional-review.md`。为保持冻结纪律，不得回改 v1 合同；修订必须进入新版本。

## 证据边界

- 50 份有效合同和 2 份异常文件均为合成测试数据，不对应真实企业、个人、账号、签章或交易。
- `construction-truth.jsonl` 只是生成时使用的构造事实，固定标记为 `construction_truth_only`，不是人工金标准。
- `gold-review-template.jsonl` 的 `review_status` 为 `pending_human_review`，有意不满足正式金标准 Schema。
- 正式评测前必须由两名真实审核人独立核对原文件，解决分歧后填写两个唯一审核人标识，并将状态改为 `agreed` 或经第三人裁决的 `adjudicated`，再另存为 `gold.jsonl`。
- 系统得分或解析失败不得用于回改当前冻结样本；修订样本必须新建数据集版本并保留本版证据。

## 生成与验证

```powershell
backend/.venv/Scripts/python.exe -m evaluation.datasets.frozen_contracts_v1.generate --output outputs/frozen-contracts-v1
backend/.venv/Scripts/python.exe -m evaluation.datasets.frozen_contracts_v1.validate --dataset outputs/frozen-contracts-v1
backend/.venv/Scripts/python.exe -m evaluation.datasets.frozen_contracts_v1.build_predictions --dataset outputs/frozen-contracts-v1
backend/.venv/Scripts/python.exe -m evaluation.datasets.frozen_contracts_v1.precheck --dataset outputs/frozen-contracts-v1
```

生成器拒绝覆盖已存在的冻结目录。`freeze-manifest.json` 绑定 53 个二进制样本的 SHA-256；`batch-manifest.json` 只包含标准 50+2，补充损坏 PDF 不计入该协议。
