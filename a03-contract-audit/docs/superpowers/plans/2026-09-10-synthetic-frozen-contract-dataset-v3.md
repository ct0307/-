# 真实企业合同冻结集 v3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. 本计划按当前会话串行执行，不使用子 agent。

**Goal:** 生成并冻结 50+2 份内容、结构、附件和文档形态均尽量贴近现实企业合同的 v3 合成测试集，同时保持 v1/v2 完整不变。

**Architecture:** v3 使用独立 Python 数据包。`cases.py` 保存 50 个逐案事实；`clauses.py` 保存风格和场景条款；`content.py` 组装合同文档；`annexes.py` 生成场景专属附件；`renderers.py` 负责 DOCX/PDF；`validate.py` 检查内容真实性、格式和冻结哈希。生成器只读取 v3 数据，不从 v1/v2 派生事实，不使用目标页数填充正文。

**Tech Stack:** Python 3、dataclasses、python-docx、PyMuPDF、现有 v1 OOXML/扫描渲染底层、pytest、SHA-256。

---

### Task 1: 建立 v3 模块骨架和模型

**Files:**
- Create: `backend/evaluation/datasets/frozen_contracts_v3/__init__.py`
- Create: `backend/evaluation/datasets/frozen_contracts_v3/models.py`
- Create: `backend/evaluation/datasets/frozen_contracts_v3/corpus-profile.json`
- Create: `backend/evaluation/datasets/frozen_contracts_v3/README.md`
- Test: `backend/tests/test_frozen_contract_dataset_v3.py`

- [ ] **Step 1: Write the failing test**

  在测试文件中加入 `test_v3_module_is_independent_and_profile_is_fixed`，断言 `load_cases()`、`load_profile()` 可导入，版本为 `3.0.0`，数量为 50+2，格式为 14/21/15，且 `cases.py` 源码不包含 `frozen_contracts_v1` 或 `frozen_contracts_v2` 导入。

- [ ] **Step 2: Run test to verify it fails**

  Run: `..venv\Scripts\python.exe -m pytest backend/tests/test_frozen_contract_dataset_v3.py::test_v3_module_is_independent_and_profile_is_fixed -q`

  Expected: FAIL with `ModuleNotFoundError` because the v3 package does not exist.

- [ ] **Step 3: Write minimal implementation**

  `models.py` 定义 `CorpusProfile`、`ContractCase`、`PartySpec`、`TruthSpec`、`AnnexSpec`、`RiskClause`、`ConflictPair`、`RevisionSet`，所有结构使用 `@dataclass(frozen=True)`；`load_profile()` 严格校验版本、数量、格式和 12 种风格分布；`corpus-profile.json` 固定写入设计文档中的分布。`__init__.py` 只导出模型和数据根路径。

- [ ] **Step 4: Run test to verify it passes**

  Run: `..venv\Scripts\python.exe -m pytest backend/tests/test_frozen_contract_dataset_v3.py::test_v3_module_is_independent_and_profile_is_fixed -q`

  Expected: PASS。

- [ ] **Step 5: Commit**

  `git add backend/evaluation/datasets/frozen_contracts_v3 backend/tests/test_frozen_contract_dataset_v3.py && git commit -m "test: scaffold frozen contract corpus v3"`

### Task 2: 显式定义 50 个真实业务案例

**Files:**
- Create: `backend/evaluation/datasets/frozen_contracts_v3/cases.py`
- Modify: `backend/tests/test_frozen_contract_dataset_v3.py`

- [ ] **Step 1: Write the failing test**

  增加 `test_v3_cases_are_explicit_and_business_complete`，断言案例编号连续、每案有不少于两方、主体角色与场景匹配、`truth` 至少包含 `subject`、`pricing`、`duration`、`payment_terms`、`delivery`、`acceptance`、`termination`，并断言八类场景数量覆盖；读取 `cases.py` AST，拒绝调用 v1/v2 `load_cases` 或按序号派生案例。

- [ ] **Step 2: Run test to verify it fails**

  Run: `..venv\Scripts\python.exe -m pytest backend/tests/test_frozen_contract_dataset_v3.py::test_v3_cases_are_explicit_and_business_complete -q`

  Expected: FAIL because no v3 cases exist。

- [ ] **Step 3: Write minimal implementation**

  在 `cases.py` 中写入 50 个 `ContractCase` 常量，按八类业务分组，每案明确合成主体、标的、计价方式、交付/验收、付款、期限、终止、风险等级、格式和风格。金额允许固定总价、单价、里程碑或 `None` 加结算公式；不少于 5 案使用三方或多方主体，不少于 10 案使用非固定总价，不少于 10 案在正文与附件之间分散关键事实。`load_cases()` 只返回这个显式元组。

- [ ] **Step 4: Run test to verify it passes**

  Run: `..venv\Scripts\python.exe -m pytest backend/tests/test_frozen_contract_dataset_v3.py::test_v3_cases_are_explicit_and_business_complete -q`

  Expected: PASS。

- [ ] **Step 5: Commit**

  `git add backend/evaluation/datasets/frozen_contracts_v3/cases.py backend/tests/test_frozen_contract_dataset_v3.py && git commit -m "feat: define explicit realistic frozen contract v3 cases"`

### Task 3: 实现独立风格和场景条款库

**Files:**
- Create: `backend/evaluation/datasets/frozen_contracts_v3/clauses.py`
- Create: `backend/evaluation/datasets/frozen_contracts_v3/annexes.py`
- Modify: `backend/tests/test_frozen_contract_dataset_v3.py`

- [ ] **Step 1: Write the failing test**

  增加 `test_v3_styles_have_substantive_differences_and_annexes_match_scenarios`，对每种风格比较章节顺序、关键义务集合和附件顺序；断言同风格案例正文不得全部相同；断言采购、SLA、工程量、租赁交接、数据目录、人力岗位等附件字段与场景匹配；禁止出现 v2 的通用三列表格字段作为唯一附件结构。

- [ ] **Step 2: Run test to verify it fails**

  Run: `..venv\Scripts\python.exe -m pytest backend/tests/test_frozen_contract_dataset_v3.py::test_v3_styles_have_substantive_differences_and_annexes_match_scenarios -q`

  Expected: FAIL，因为条款库尚未实现。

- [ ] **Step 3: Write minimal implementation**

  `clauses.py` 为 12 种风格分别声明章节顺序、定义段、义务偏向、违约和签署措辞；每种风格至少有 8 个可组合但不互相复制的条款模块。`annexes.py` 为八类场景声明不同的附件构造器和字段 schema，返回 `AnnexSpec`，并把正文引用、版本号和优先级写入附件元数据。

- [ ] **Step 4: Run test to verify it passes**

  Run: `..venv\Scripts\python.exe -m pytest backend/tests/test_frozen_contract_dataset_v3.py::test_v3_styles_have_substantive_differences_and_annexes_match_scenarios -q`

  Expected: PASS。

- [ ] **Step 5: Commit**

  `git add backend/evaluation/datasets/frozen_contracts_v3/clauses.py backend/evaluation/datasets/frozen_contracts_v3/annexes.py backend/tests/test_frozen_contract_dataset_v3.py && git commit -m "feat: add substantive v3 clause styles and business annexes"`

### Task 4: 生成真实正文模型

**Files:**
- Create: `backend/evaluation/datasets/frozen_contracts_v3/content.py`
- Modify: `backend/tests/test_frozen_contract_dataset_v3.py`

- [ ] **Step 1: Write the failing test**

  增加 `test_v3_documents_meet_realistic_length_and_obligation_thresholds`，断言短单、普通合同和长合同分别满足 1,200–1,800、至少 2,500、至少 6,000 中文字符；每案至少包含 10 个独立实质义务或交易动作；正文不含连续重复段落，且 `target_pages` 不存在于 `ContractDocument` 和正文生成路径。

- [ ] **Step 2: Run test to verify it fails**

  Run: `..venv\Scripts\python.exe -m pytest backend/tests/test_frozen_contract_dataset_v3.py::test_v3_documents_meet_realistic_length_and_obligation_thresholds -q`

  Expected: FAIL，因为没有 v3 正文构造器。

- [ ] **Step 3: Write minimal implementation**

  `content.py` 定义 `ContractSection` 和 `ContractDocument`，按案例的场景和风格组合定义、主体、标的、交付、验收、付款、变更、质量/SLA、保密、数据/IP、合规、安全、责任、终止、争议解决、签署和附件引用。正文长度由真实模块数量和案例事实自然决定，不允许用页数循环填充。正文标题与合同类型相称，短式订单不强行加入无关章节。

- [ ] **Step 4: Run test to verify it passes**

  Run: `..venv\Scripts\python.exe -m pytest backend/tests/test_frozen_contract_dataset_v3.py::test_v3_documents_meet_realistic_length_and_obligation_thresholds -q`

  Expected: PASS。

- [ ] **Step 5: Commit**

  `git add backend/evaluation/datasets/frozen_contracts_v3/content.py backend/tests/test_frozen_contract_dataset_v3.py && git commit -m "feat: compose realistic v3 contract bodies"`

### Task 5: 接入隔离的 DOCX/PDF 渲染和修订结构

**Files:**
- Create: `backend/evaluation/datasets/frozen_contracts_v3/renderers.py`
- Create: `backend/evaluation/datasets/frozen_contracts_v3/ooxml.py`
- Modify: `backend/tests/test_frozen_contract_dataset_v3.py`

- [ ] **Step 1: Write the failing test**

  增加 `test_v3_render_modes_and_revision_xml`，断言 DOCX 可读且修订案包含 `w:trackRevisions`、`w:ins`、`w:del`、批注关系；文本 PDF 有文本层；扫描 PDF 无文本层但有图像；混合 PDF 同时有有文本页和无文本页。

- [ ] **Step 2: Run test to verify it fails**

  Run: `..venv\Scripts\python.exe -m pytest backend/tests/test_frozen_contract_dataset_v3.py::test_v3_render_modes_and_revision_xml -q`

  Expected: FAIL，因为 v3 渲染器不存在。

- [ ] **Step 3: Write minimal implementation**

  渲染器调用现有 v1 的底层排版和扫描 profile，但通过 v3 `ContractDocument` 适配器隔离；不复制 v2 的内容生成。OOXML 注入只处理 v3 `RevisionSet`，固定作者、日期和修订文本，不生成真人信息。

- [ ] **Step 4: Run test to verify it passes**

  Run: `..venv\Scripts\python.exe -m pytest backend/tests/test_frozen_contract_dataset_v3.py::test_v3_render_modes_and_revision_xml -q`

  Expected: PASS。

- [ ] **Step 5: Commit**

  `git add backend/evaluation/datasets/frozen_contracts_v3/renderers.py backend/evaluation/datasets/frozen_contracts_v3/ooxml.py backend/tests/test_frozen_contract_dataset_v3.py && git commit -m "feat: render authentic v3 contract formats"`

### Task 6: 生成 50+2、预测真值和冻结清单

**Files:**
- Create: `backend/evaluation/datasets/frozen_contracts_v3/generate.py`
- Create: `backend/evaluation/datasets/frozen_contracts_v3/build_predictions.py`
- Create: `backend/evaluation/datasets/frozen_contracts_v3/precheck.py`
- Modify: `backend/tests/test_frozen_contract_dataset_v3.py`

- [ ] **Step 1: Write the failing test**

  增加 `test_v3_generation_freezes_50_plus_2_without_overwrite`，断言生成结果为 50 valid、2 invalid、1 supplemental、53 个唯一哈希，manifest 包含 `construction_truth_only` 和 `formal_gold=false`，再次生成同一目录抛出 `FileExistsError`，且 v1/v2 哈希未变化。

- [ ] **Step 2: Run test to verify it fails**

  Run: `..venv\Scripts\python.exe -m pytest backend/tests/test_frozen_contract_dataset_v3.py::test_v3_generation_freezes_50_plus_2_without_overwrite -q`

  Expected: FAIL，因为生成入口不存在。

- [ ] **Step 3: Write minimal implementation**

  `generate.py` 创建独立输出目录，按案例格式渲染合同，写入无效/补充样本、manifest、batch manifest、construction truth、human review template 和 README。`build_predictions.py` 只在已生成文件存在时构造技术预测；`precheck.py` 沿用非正式构造真值标识，不生成伪造 reviewers。

- [ ] **Step 4: Run test to verify it passes**

  Run: `..venv\Scripts\python.exe -m pytest backend/tests/test_frozen_contract_dataset_v3.py::test_v3_generation_freezes_50_plus_2_without_overwrite -q`

  Expected: PASS。

- [ ] **Step 5: Commit**

  `git add backend/evaluation/datasets/frozen_contracts_v3/generate.py backend/evaluation/datasets/frozen_contracts_v3/build_predictions.py backend/evaluation/datasets/frozen_contracts_v3/precheck.py backend/tests/test_frozen_contract_dataset_v3.py && git commit -m "feat: generate and freeze v3 contract corpus"`

### Task 7: 实现真实性校验器和失败报告

**Files:**
- Create: `backend/evaluation/datasets/frozen_contracts_v3/validate.py`
- Modify: `backend/tests/test_frozen_contract_dataset_v3.py`

- [ ] **Step 1: Write the failing test**

  增加 `test_v3_validator_rejects_sparse_duplicate_or_mismatched_documents`，分别篡改一个正文为短文本、把附件改成错误场景、把两个正文变成高相似文本，断言 `validate_dataset()` 抛出带具体 case id 和原因的 `ValueError`，并生成 `validation-report.json`。

- [ ] **Step 2: Run test to verify it fails**

  Run: `..venv\Scripts\python.exe -m pytest backend/tests/test_frozen_contract_dataset_v3.py::test_v3_validator_rejects_sparse_duplicate_or_mismatched_documents -q`

  Expected: FAIL，因为校验器尚未实现真实性规则。

- [ ] **Step 3: Write minimal implementation**

  `validate.py` 校验文件哈希、案例映射、DOCX/PDF 可读性、页面字符密度、空白比例、最小正文长度、独立义务关键词数量、重复段落比例、风格结构差异、附件场景匹配、冲突双方文本、修订 XML 和无效样本。页数只写入报告，不作为正文生成输入。

- [ ] **Step 4: Run test to verify it passes**

  Run: `..venv\Scripts\python.exe -m pytest backend/tests/test_frozen_contract_dataset_v3.py::test_v3_validator_rejects_sparse_duplicate_or_mismatched_documents -q`

  Expected: PASS。

- [ ] **Step 5: Commit**

  `git add backend/evaluation/datasets/frozen_contracts_v3/validate.py backend/tests/test_frozen_contract_dataset_v3.py && git commit -m "test: enforce realistic v3 corpus validation"`

### Task 8: 运行专项测试、生成输出并做视觉抽样

**Files:**
- Modify: `backend/evaluation/datasets/frozen_contracts_v3/README.md`
- Create: `outputs/frozen-contracts-v3/`（本地验收输出，不提交 Git）

- [ ] **Step 1: Run focused tests**

  Run: `..venv\Scripts\python.exe -m pytest backend/tests/test_frozen_contract_dataset_v3.py -q`

  Expected: all v3 tests PASS。

- [ ] **Step 2: Generate the frozen corpus**

  Run: `..venv\Scripts\python.exe -m evaluation.datasets.frozen_contracts_v3.generate --output outputs/frozen-contracts-v3`

  Expected: output reports `valid=50 invalid=2 supplemental=1`。

- [ ] **Step 3: Validate and build technical predictions**

  Run: `..venv\Scripts\python.exe -m evaluation.datasets.frozen_contracts_v3.validate --dataset outputs/frozen-contracts-v3` and `..venv\Scripts\python.exe -m evaluation.datasets.frozen_contracts_v3.build_predictions --dataset outputs/frozen-contracts-v3`

  Expected: validation status `passed`; predictions report remains explicitly non-formal。

- [ ] **Step 4: Inspect representative files**

  抽样检查一份 DOCX、一份文本 PDF、一份扫描 PDF、一份混合 PDF 的正文字符密度、页面空白比例、中文可读性、附件标题和签署页；若 Word/Poppler/OCR 环境阻塞，保存命令输出并把相应项标为 `blocked`，不得改写成通过。

- [ ] **Step 5: Commit source-only changes**

  `git status --short` 应确认 `outputs/` 未被 Git 跟踪；只提交 v3 源代码、测试、README 和报告 schema，不提交合同原件、日志、数据库或密钥。

### Task 9: 完整质量门禁和最终验收

**Files:**
- Modify: `.planning/frozen-contracts-v3/task_plan.md`、`.planning/frozen-contracts-v3/progress.md`、`.planning/frozen-contracts-v3/findings.md`（如当前工作树配置了规划目录）
- Modify: `backend/evaluation/datasets/frozen_contracts_v3/README.md`

- [ ] **Step 1: Run project checks**

  Run: `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\quality_gate.ps1`，必要时另行运行后端测试、类型检查和文档结构检查。

- [ ] **Step 2: Verify version isolation**

  重新计算 v1 `cases.json` 和 `corpus-profile.json` 的 SHA-256，与冻结基线完全一致；检查 v2 分支提交和输出目录没有被修改。

- [ ] **Step 3: Write final acceptance report**

  记录 P0/P1 通过项、未实测项、阻塞证据、输出 manifest 路径、提交号和残余风险。最终只能表述为“合成、接近真实业务结构的 v3 测试集”，不能表述为真实企业合同金标准或真人复核通过。

- [ ] **Step 4: Commit documentation**

  `git add backend/evaluation/datasets/frozen_contracts_v3 backend/tests/test_frozen_contract_dataset_v3.py docs/superpowers/plans/2026-09-10-synthetic-frozen-contract-dataset-v3.md && git commit -m "docs: record frozen contract v3 verification"`

