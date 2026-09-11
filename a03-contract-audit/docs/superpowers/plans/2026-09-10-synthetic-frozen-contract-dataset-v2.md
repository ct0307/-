# Realistic Synthetic Frozen Contract Dataset v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不修改 v1 的前提下，生成并冻结具有真实风险原文、实际条款冲突和 DOCX 修订结构的 50+2 合同集 v2。

**Architecture:** `frozen_contracts_v2` 使用独立画像、案例模型、内容组装和渲染代码。案例事实显式保存风险、冲突、附件和修订集合；验证器读取最终文件做语义与 OOXML 检查。全部文件冻结后，预测模块才调用生产解析器。

**Tech Stack:** Python、pytest、python-docx、PyMuPDF、Pillow、OOXML、现有 evaluation 与质量门禁脚本；不新增依赖。

---

## 文件职责

| 文件 | 职责 |
|---|---|
| `backend/evaluation/datasets/frozen_contracts_v2/models.py` | 严格加载画像、风险、冲突、附件和修订模型 |
| `backend/evaluation/datasets/frozen_contracts_v2/cases.py` | 50 个明确案例事实及 12 种风格分布 |
| `backend/evaluation/datasets/frozen_contracts_v2/clauses.py` | 风格化正文模块和真实风险条款 |
| `backend/evaluation/datasets/frozen_contracts_v2/content.py` | 组装正文、业务附件、冲突位置和修订锚点 |
| `backend/evaluation/datasets/frozen_contracts_v2/ooxml.py` | 向 DOCX 注入确定性修订、批注和关系 |
| `backend/evaluation/datasets/frozen_contracts_v2/renderers.py` | DOCX、文本 PDF、扫描和混合 PDF 渲染 |
| `backend/evaluation/datasets/frozen_contracts_v2/generate.py` | 生成 50+2、补充样本、真值和冻结清单 |
| `backend/evaluation/datasets/frozen_contracts_v2/validate.py` | 文件级语义、OOXML、相似度、隐私和哈希校验 |
| `backend/evaluation/datasets/frozen_contracts_v2/build_predictions.py` | 冻结后生产解析预测 |
| `backend/evaluation/datasets/frozen_contracts_v2/precheck.py` | 分层构造真值技术预评测 |
| `backend/tests/test_frozen_contract_dataset_v2.py` | v2 专项 TDD 回归 |

### Task 1: 独立模型和固定画像

**Files:** Create `backend/evaluation/datasets/frozen_contracts_v2/{__init__.py,models.py,corpus-profile.json}`; Test `backend/tests/test_frozen_contract_dataset_v2.py`

- [ ] 写失败测试，断言 `F2-001..F2-050`、14/21/15、12 种风格、28/14/8 风险等级，以及 v1 manifest 哈希未改变。
- [ ] 运行 `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_frozen_contract_dataset_v2.py -q`，确认因 v2 包不存在而失败。
- [ ] 实现不可变模型：

```python
@dataclass(frozen=True)
class RiskClause:
    clause_id: str
    text: str
    risk_type: str
    favored_party: str | None
    severity: str
    review_reason: str
    evidence_location: str

@dataclass(frozen=True)
class ConflictPair:
    source_a: str
    text_a: str
    source_b: str
    text_b: str
    precedence_rule: str
    effective_value: str
```

- [ ] 运行专项测试确认画像通过，提交 `test: define frozen contract v2 invariants`。

### Task 2: 50 个案例事实

**Files:** Create `backend/evaluation/datasets/frozen_contracts_v2/{cases.py,source-register.md}`; Modify test file

- [ ] 写失败测试，逐项检查附件数量、三方数量、长文档数量、6 个冲突和 4 个修订案例，且风险原文不是“应当关注/建议审查”等说明性文字。
- [ ] 定义 50 个显式 `ContractCase`，不通过循环派生主体、金额、风险或冲突事实；每个冲突对写入两段完整合同原文。
- [ ] 运行测试，提交 `feat: define realistic frozen contract v2 cases`。

### Task 3: 风格化正文与业务附件

**Files:** Create `backend/evaluation/datasets/frozen_contracts_v2/{clauses.py,content.py}`; Modify test file

- [ ] 写失败测试，断言 12 种风格拥有不同章节签名，风险原文和冲突双方出现在声明位置，长合同没有“履约控制与证据清单”通用填充。
- [ ] 实现 `build_contract(case)`，由风格策略选择章节、顺序、立场和业务附件：

```python
STYLE_BUILDERS: dict[str, Callable[[ContractCase], tuple[ContractSection, ...]]] = {
    "buyer_standard": build_buyer_standard,
    "supplier_standard": build_supplier_standard,
    "business_draft": build_business_draft,
    "legal_redline": build_legal_redline,
    "model_contract": build_model_contract,
    "online_terms": build_online_terms,
    "framework_order": build_framework_order,
    "master_supplement": build_master_supplement,
    "project_conditions": build_project_conditions,
    "industry_template": build_industry_template,
    "customer_template": build_customer_template,
    "short_order": build_short_order,
}
```

- [ ] 用设备表、价格表、SLA、工程量、人员表等案例数据生成附件；运行测试并提交 `feat: compose style-specific frozen contracts v2`。

### Task 4: 真实 DOCX 修订结构

**Files:** Create `backend/evaluation/datasets/frozen_contracts_v2/{ooxml.py,renderers.py}`; Modify test file

- [ ] 写失败测试，打开生成的四个 DOCX ZIP，断言 `trackRevisions`、`w:ins`、`w:del`、`comments.xml`、comments relationship 和批注范围均存在。
- [ ] 写失败测试，分别提取 all-changes 与 accepted 文本，断言删除文本只在前者、插入文本在两者，且与 `revision_set` 一致。
- [ ] 先用 python-docx 生成 A4 文档，再通过 ZIP/ElementTree 确定性修改 OOXML；作者固定为 `Codex（合成法务修订）`，日期来自案例事实。
- [ ] 运行修订专项测试，提交 `feat: render authentic docx revisions for corpus v2`。

### Task 5: PDF、扫描和完整格式渲染

**Files:** Modify `renderers.py`; Modify test file

- [ ] 写失败测试，验证文本 PDF 有文本层、纯扫描 PDF 无文本层、混合 PDF 两类页面并存，所有页可打开且不溢出。
- [ ] 使用固定字体、元数据和 `ScanProfile` 实现三类 PDF；只使用现有 PyMuPDF/Pillow。
- [ ] 运行格式测试，提交 `feat: render frozen contract v2 formats`。

### Task 6: 生成、冻结和文件级验证

**Files:** Create `backend/evaluation/datasets/frozen_contracts_v2/{generate.py,validate.py,README.md}`; Modify test file

- [ ] 写失败测试，断言 50 valid、2 invalid、1 supplemental、拒绝覆盖、全部哈希唯一和 v1 manifest 哈希不变。
- [ ] 写篡改测试，并让验证器检查最终文件中的风险原文、冲突双值、附件归属、OOXML、页数、隐私和归一化相似度。
- [ ] 实现生成与验证，输出 `construction-truth.jsonl` 和保持 `pending_human_review` 的审核模板。
- [ ] 运行专项测试，提交 `feat: freeze and validate contract corpus v2`。

### Task 7: 正式生成与视觉复核

**Files:** Generate ignored `outputs/frozen-contracts-v2/`; Update `.planning/frozen-contracts-v2/progress.md`

- [ ] 运行全部 v2 专项测试且零失败。
- [ ] 从 `backend/` 运行 `./.venv/Scripts/python.exe -m evaluation.datasets.frozen_contracts_v2.generate --output ../outputs/frozen-contracts-v2`，只生成一次。
- [ ] 运行 v2 validate，保存报告且不得因失败回改冻结文件。
- [ ] 将全部 PDF 和 Word 转换稿逐页渲染，检查空白、裁切、重叠、乱码、修订标记和附件表格；保存截图索引。

### Task 8: 冻结后解析与分层预评测

**Files:** Create `backend/evaluation/datasets/frozen_contracts_v2/{build_predictions.py,precheck.py}`; Modify test file

- [ ] 写失败测试，断言预测始终保留 50 个分母，预评测固定 `construction_truth_only`，并按三个风险层级报告。
- [ ] 实现生产解析预测和分层预评测；生成器和内容模块不得导入生产解析器。
- [ ] 冻结后运行预测与预评测，原样记录 OCR 失败和实际分数，提交 `feat: precheck frozen contract corpus v2`。

### Task 9: 服务验收与完整门禁

**Files:** Generate ignored API evidence; Update dataset README and planning files

- [ ] 只读审计令牌、Redis、Celery、后端和 LLM 条件；缺失时写 blocked manifest，不使用 mock 替代。
- [ ] 条件具备时运行真实 50+2 批测及 `S2-001` 异步失败隔离。
- [ ] 运行 `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/quality_gate.ps1`，要求所有阶段退出码 0。
- [ ] 运行 `git diff --check`、`git status --short` 和 v1/v2 哈希核对，提交最终证据文档。
