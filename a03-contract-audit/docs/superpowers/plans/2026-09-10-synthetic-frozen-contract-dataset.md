# High-Fidelity Synthetic Frozen Contract Dataset Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建不迎合当前解析器的 50+2 高拟真合成冻结合同集，完成静态验证、生产解析、OCR、构造真值技术预评测，并在环境允许时执行真实批次 API 验收。

**Architecture:** 以 `corpus-profile.json` 和 `cases.json` 作为先验事实源；内容组装器只依据交易画像构建条款，渲染器分别生成 DOCX、文本 PDF 和扫描/混合 PDF。生成后先写 SHA-256 冻结清单，再由独立验证器和生产解析器读取；评测结果不得反向修改当前冻结版本。

**Tech Stack:** Python 3.11/3.13、pytest、python-docx 1.1.2、PyMuPDF 1.25.5、现有 RapidOCR、现有 `evaluation` 证据模块和 FastAPI/Celery 批次接口。

---

## 文件职责

| 文件 | 职责 |
|---|---|
| `backend/evaluation/datasets/__init__.py` | 数据集包入口 |
| `backend/evaluation/datasets/frozen_contracts_v1/__init__.py` | 导出数据集根路径与版本 |
| `backend/evaluation/datasets/frozen_contracts_v1/source-register.md` | 权威公开结构来源与非复制边界 |
| `backend/evaluation/datasets/frozen_contracts_v1/corpus-profile.json` | 冻结前声明总体数量、格式、场景和防迎合比例 |
| `backend/evaluation/datasets/frozen_contracts_v1/cases.json` | 50 个案例的显式业务事实、版式、缺失值、附件和风险标签 |
| `backend/evaluation/datasets/frozen_contracts_v1/models.py` | 加载并校验画像和案例数据 |
| `backend/evaluation/datasets/frozen_contracts_v1/content.py` | 按业务事实组装原创合同章节和附件 |
| `backend/evaluation/datasets/frozen_contracts_v1/renderers.py` | DOCX、文本 PDF、扫描/混合 PDF 渲染 |
| `backend/evaluation/datasets/frozen_contracts_v1/generate.py` | 生成 50+2、补充样本、construction truth 与冻结清单 |
| `backend/evaluation/datasets/frozen_contracts_v1/validate.py` | 数量、哈希、格式、页数、隐私、相似度和防迎合校验 |
| `backend/evaluation/datasets/frozen_contracts_v1/build_predictions.py` | 调用生产解析器生成预测，不修改冻结输入 |
| `backend/evaluation/datasets/frozen_contracts_v1/precheck.py` | 对 construction truth 运行明确标记的技术预评测 |
| `backend/tests/test_frozen_contract_dataset.py` | 数据、生成、冻结、验证和预评测回归测试 |

本地输出固定为 `outputs/frozen-contracts-v1/`，由根 `.gitignore` 忽略。

除非步骤另有说明，所有命令均从 `a03-contract-audit/` 项目目录执行。

### Task 1: 数据模型与画像约束

**Files:**
- Create: `a03-contract-audit/backend/evaluation/datasets/__init__.py`
- Create: `a03-contract-audit/backend/evaluation/datasets/frozen_contracts_v1/__init__.py`
- Create: `a03-contract-audit/backend/evaluation/datasets/frozen_contracts_v1/models.py`
- Test: `a03-contract-audit/backend/tests/test_frozen_contract_dataset.py`

- [ ] **Step 1: 写画像加载失败测试**

```python
def test_profile_requires_exact_realistic_distribution(tmp_path):
    profile = valid_profile()
    profile["formats"] = {"docx": 30, "text_pdf": 15, "scanned_or_mixed_pdf": 5}
    path = write_json(tmp_path / "corpus-profile.json", profile)
    with pytest.raises(ValueError, match="格式分布"):
        load_profile(path)
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_frozen_contract_dataset.py::test_profile_requires_exact_realistic_distribution -q`

Expected: FAIL，原因是 `load_profile` 尚不存在。

- [ ] **Step 3: 实现不可变数据模型与校验器**

```python
@dataclass(frozen=True)
class CorpusProfile:
    version: str
    valid_count: int
    invalid_count: int
    formats: Mapping[str, int]
    scenarios: Mapping[str, int]
    anti_fit: Mapping[str, float]

def load_profile(path: Path) -> CorpusProfile:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload["valid_count"] != 50 or payload["invalid_count"] != 2:
        raise ValueError("数据集必须为 50+2")
    if payload["formats"] != {
        "docx": 14,
        "text_pdf": 21,
        "scanned_or_mixed_pdf": 15,
    }:
        raise ValueError("格式分布不符合冻结设计")
    return CorpusProfile(**payload)
```

- [ ] **Step 4: 补充案例唯一性、枚举和比例测试并运行**

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_frozen_contract_dataset.py -q`

Expected: Task 1 测试全部 PASS。

- [ ] **Step 5: 提交**

```powershell
git add -- backend/evaluation/datasets backend/tests/test_frozen_contract_dataset.py
git commit -m "test: define frozen contract corpus invariants"
```

### Task 2: 权威来源、语料画像与 50 个案例事实

**Files:**
- Create: `a03-contract-audit/backend/evaluation/datasets/frozen_contracts_v1/source-register.md`
- Create: `a03-contract-audit/backend/evaluation/datasets/frozen_contracts_v1/corpus-profile.json`
- Create: `a03-contract-audit/backend/evaluation/datasets/frozen_contracts_v1/cases.json`
- Modify: `a03-contract-audit/backend/tests/test_frozen_contract_dataset.py`

- [ ] **Step 1: 写完整语料断言**

```python
def test_cases_match_frozen_profile_and_are_not_parser_friendly():
    profile = load_profile(DATASET_ROOT / "corpus-profile.json")
    cases = load_cases(DATASET_ROOT / "cases.json")
    assert [case.case_id for case in cases] == [f"FC-{i:03d}" for i in range(1, 51)]
    assert dict(Counter(case.format for case in cases)) == dict(profile.formats)
    assert sum(case.primary_roles != ("甲方", "乙方") for case in cases) >= 20
    assert sum(case.amount_heading != "合同金额" for case in cases) >= 15
    assert sum(case.truth["amount"] is None for case in cases) >= 10
    assert sum(bool(case.related_documents) for case in cases) >= 4
```

- [ ] **Step 2: 运行断言并确认数据文件缺失**

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_frozen_contract_dataset.py -q`

Expected: FAIL，指出 `corpus-profile.json` 或 `cases.json` 不存在。

- [ ] **Step 3: 写来源登记和语料画像**

`corpus-profile.json` 必须固定以下核心数据：

```json
{
  "version": "1.0.0",
  "valid_count": 50,
  "invalid_count": 2,
  "formats": {"docx": 14, "text_pdf": 21, "scanned_or_mixed_pdf": 15},
  "anti_fit": {
    "non_party_ab_ratio": 0.4,
    "non_contract_amount_heading_ratio": 0.3,
    "nullable_or_formula_amount_ratio": 0.2,
    "distributed_field_ratio": 0.2,
    "clause_conflict_ratio": 0.1
  }
}
```

`source-register.md` 记录规格中的六个已核验官方来源、访问日期和“只借鉴结构、不复制全文”边界。

- [ ] **Step 4: 写 50 个显式案例记录**

每个 `cases.json` 记录必须包含以下结构，且具体值在写入时完整给出：

```json
{
  "case_id": "FC-001",
  "title": "工业相机及配套镜头采购合同",
  "scenario": "采购、供货与销售",
  "contract_type": "采购合同",
  "format": "text_pdf",
  "render_mode": "native",
  "document_state": "signed_final",
  "primary_roles": ["采购人", "供应商"],
  "parties": ["之江测试智能制造有限公司", "星澜测试光电科技有限公司"],
  "price_model": "fixed_total_tax_included",
  "amount_heading": "价税合计",
  "truth": {
    "party_a": "之江测试智能制造有限公司",
    "party_b": "星澜测试光电科技有限公司",
    "subject": "工业相机及配套镜头采购、安装与调试",
    "amount": "人民币1286000元（含税）",
    "duration": "2026年10月1日至2027年3月31日",
    "payment_terms": ["预付款20%", "到货验收后支付70%", "质保期满支付10%"]
  },
  "related_documents": ["附件一：设备清单", "附件二：验收规范"],
  "risk_tags": ["验收标准解释权", "逾期付款责任不对等"],
  "target_pages": 8,
  "layout_variant": "cover_table_annex",
  "source_profiles": ["samr-sale-order"]
}
```

按规格逐项满足 8 类业务数量、14/21/15 格式、页数、附件、多方、缺失值和版本关系，不用循环在运行时派生业务事实。

- [ ] **Step 5: 运行语料测试并提交**

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_frozen_contract_dataset.py -q`

Expected: PASS，50 个案例和全部比例匹配画像。

```powershell
git add -- backend/evaluation/datasets/frozen_contracts_v1 backend/tests/test_frozen_contract_dataset.py
git commit -m "feat: define realistic frozen contract corpus"
```

### Task 3: 原创合同内容组装

**Files:**
- Create: `a03-contract-audit/backend/evaluation/datasets/frozen_contracts_v1/content.py`
- Modify: `a03-contract-audit/backend/tests/test_frozen_contract_dataset.py`

- [ ] **Step 1: 写内容独立性和现实结构测试**

```python
def test_contract_content_uses_case_profile_without_uniform_parser_headings():
    cases = load_cases(DATASET_ROOT / "cases.json")
    documents = [build_contract(case) for case in cases]
    assert all(len(doc.sections) >= 10 for doc in documents)
    assert sum("甲方：" not in doc.plain_text for doc in documents) >= 20
    assert sum("合同金额：" not in doc.plain_text for doc in documents) >= 15
    assert all("合成测试样本" in doc.plain_text for doc in documents)
    assert max_pairwise_similarity(doc.plain_text for doc in documents) < 0.92
```

- [ ] **Step 2: 确认测试因内容组装器缺失而失败**

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_frozen_contract_dataset.py -q`

Expected: FAIL，`build_contract` 尚不存在。

- [ ] **Step 3: 实现按场景分派的内容组装器**

```python
@dataclass(frozen=True)
class ContractDocument:
    title: str
    header_lines: tuple[str, ...]
    sections: tuple[ContractSection, ...]
    annexes: tuple[ContractSection, ...]

    @property
    def plain_text(self) -> str:
        blocks = [self.title, *self.header_lines]
        blocks.extend(section.as_text() for section in (*self.sections, *self.annexes))
        return "\n".join(blocks)

BUILDERS = {
    "采购、供货与销售": build_sale_contract,
    "技术、软件与数据服务": build_technology_contract,
    "运维、咨询、培训与业务外包": build_service_contract,
    "房屋、设备与场地租赁": build_lease_contract,
    "建设、装修、监理与承揽": build_construction_contract,
    "人力资源、保险与员工服务": build_employee_service_contract,
    "保密、数据处理与知识产权": build_confidentiality_contract,
    "框架订单、补充协议与多方合作": build_related_document,
}
```

各 builder 使用独立条款池和案例标签选择条款，不导入 `app.services.parser.extractor`，不读取其正则或提示词。

- [ ] **Step 4: 运行内容测试并提交**

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_frozen_contract_dataset.py -q`

Expected: PASS，结构和相似度约束通过。

```powershell
git add -- backend/evaluation/datasets/frozen_contracts_v1/content.py backend/tests/test_frozen_contract_dataset.py
git commit -m "feat: compose diverse synthetic contract content"
```

### Task 4: DOCX、文本 PDF 和扫描 PDF 渲染

**Files:**
- Create: `a03-contract-audit/backend/evaluation/datasets/frozen_contracts_v1/renderers.py`
- Modify: `a03-contract-audit/backend/tests/test_frozen_contract_dataset.py`

- [ ] **Step 1: 写三类渲染器文件特征测试**

```python
def test_renderers_create_native_and_image_only_documents(tmp_path):
    document = sample_contract_document()
    docx_path = render_docx(document, tmp_path / "sample.docx", draft_mark="内部审阅稿")
    pdf_path = render_text_pdf(document, tmp_path / "sample.pdf")
    scan_path = render_scanned_pdf(document, tmp_path / "scan.pdf", profile=ScanProfile.light())
    assert "合成测试样本" in Document(docx_path).paragraphs[0].text
    with fitz.open(pdf_path) as pdf:
        assert sum(len(page.get_text()) for page in pdf) > 500
    with fitz.open(scan_path) as pdf:
        assert sum(len(page.get_text()) for page in pdf) == 0
        assert all(page.get_images() for page in pdf)
```

- [ ] **Step 2: 运行测试并确认渲染器缺失**

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_frozen_contract_dataset.py -q`

Expected: FAIL，三个渲染函数尚不存在。

- [ ] **Step 3: 实现 A4 DOCX 与文本 PDF 渲染**

DOCX 显式设置 A4、页边距、宋体/微软雅黑、标题、表格列宽、页码与测试标识。文本 PDF 从 `C:/Windows/Fonts/msyh.ttc` 或可配置 `CONTRACT_TEST_FONT` 加载中文字体；字体缺失时明确失败，不回退成乱码。

```python
def resolve_cjk_font() -> Path:
    candidates = [os.getenv("CONTRACT_TEST_FONT"), "C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simsun.ttc"]
    for value in candidates:
        if value and Path(value).is_file():
            return Path(value)
    raise RuntimeError("未找到可嵌入的中文字体")
```

- [ ] **Step 4: 实现固定扰动扫描/混合 PDF**

先生成无敏感信息的临时文本页，在内存中按固定 DPI 栅格化，再创建只含页面图片的新 PDF。`ScanProfile` 固定 DPI、旋转角、亮度、压缩和边缘阴影；混合模式按案例声明保留部分文本页。关闭所有 PyMuPDF 文档对象，临时字节不落盘。

- [ ] **Step 5: 运行专项测试并提交**

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_frozen_contract_dataset.py -q`

Expected: PASS，三类文件可打开且文本层特征符合预期。

```powershell
git add -- backend/evaluation/datasets/frozen_contracts_v1/renderers.py backend/tests/test_frozen_contract_dataset.py
git commit -m "feat: render realistic contract document formats"
```

### Task 5: 生成、冻结和拒绝静默覆盖

**Files:**
- Create: `a03-contract-audit/backend/evaluation/datasets/frozen_contracts_v1/generate.py`
- Create: `a03-contract-audit/backend/evaluation/datasets/frozen_contracts_v1/README.md`
- Modify: `a03-contract-audit/backend/tests/test_frozen_contract_dataset.py`

- [ ] **Step 1: 写生成数量、清单和不可覆盖测试**

```python
def test_generate_freezes_exact_50_plus_2_and_refuses_overwrite(tmp_path):
    result = generate_dataset(tmp_path)
    assert result.valid_count == 50
    assert result.invalid_count == 2
    assert len(result.manifest["files"]) == 53  # 含 SX-001 补充损坏 PDF
    assert all(len(row["sha256"]) == 64 for row in result.manifest["files"])
    with pytest.raises(FileExistsError, match="冻结目录已存在"):
        generate_dataset(tmp_path)
```

- [ ] **Step 2: 确认测试失败后实现生成入口**

```python
def generate_dataset(output_root: Path) -> GenerationResult:
    if output_root.exists():
        raise FileExistsError(f"冻结目录已存在: {output_root}")
    output_root.mkdir(parents=True)
    # 逐案例 build -> render -> hash；完成后原子写入 manifest。
```

生成 `FX-051-empty-corrupt.pdf`、`FX-052-spoofed.pdf.exe` 和非空损坏 `SX-001-nonempty-corrupt.pdf`。`batch-manifest.json` 只含 50+2，并使用相对路径与实际 SHA-256。

- [ ] **Step 3: 生成 construction truth 和人工审核模板**

`construction-truth.jsonl` 不含 `reviewers`；`gold-review-template.jsonl` 明确使用 `review_status: "pending_human_review"`，因此有意不满足正式 Schema，README 必须说明填写并转为 `gold.jsonl` 的人工步骤。

- [ ] **Step 4: 运行生成测试并提交**

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_frozen_contract_dataset.py -q`

Expected: PASS，第二次生成被拒绝。

```powershell
git add -- backend/evaluation/datasets/frozen_contracts_v1 backend/tests/test_frozen_contract_dataset.py
git commit -m "feat: generate and freeze synthetic contract corpus"
```

### Task 6: 静态验证、预测与技术预评测

**Files:**
- Create: `a03-contract-audit/backend/evaluation/datasets/frozen_contracts_v1/validate.py`
- Create: `a03-contract-audit/backend/evaluation/datasets/frozen_contracts_v1/build_predictions.py`
- Create: `a03-contract-audit/backend/evaluation/datasets/frozen_contracts_v1/precheck.py`
- Modify: `a03-contract-audit/backend/tests/test_frozen_contract_dataset.py`

- [ ] **Step 1: 写篡改、隐私、重复内容和正式评测隔离测试**

```python
def test_validator_rejects_hash_tampering(tmp_path):
    root = generate_dataset(tmp_path / "frozen").root
    first = next((root / "contracts").iterdir())
    first.write_bytes(first.read_bytes() + b"tampered")
    with pytest.raises(ValueError, match="SHA-256"):
        validate_dataset(root)

def test_construction_precheck_never_claims_formal_gold():
    report = evaluate_construction_truth([truth_row()], {"FC-001": prediction_row()})
    assert report["evidence_level"] == "construction_truth_only"
    assert report["formal_gold"] is False
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_frozen_contract_dataset.py -q`

Expected: FAIL，验证和预评测函数尚不存在。

- [ ] **Step 3: 实现独立静态验证器**

验证 50+2 计数、SHA-256、MIME/扩展名、页数、文本层、空文件、画像比例、重复哈希、归一化正文相似度、虚构命名约束和身份证/银行卡模式。输出 `validation-report.json`，失败时保留所有原因并返回非零。

- [ ] **Step 4: 实现生产解析预测**

```python
def build_predictions(dataset_root: Path) -> list[dict[str, object]]:
    predictions = []
    for case in load_cases(DATASET_ROOT / "cases.json"):
        path = dataset_root / "contracts" / case.filename
        parsed = extract_document(str(path))
        fields = extract_elements(parsed.text)
        predictions.append({"case_id": case.case_id, "prediction": project_six_fields(fields), "parse": parse_metadata(parsed)})
    return predictions
```

批量路径使用生产代码当前实际采用的 `extract_elements`，单份精解析结果可作为单列补充，不混入同一预测分数。

- [ ] **Step 5: 实现 construction truth 预评测**

复用 `normalize_scalar`、`scalar_accuracy` 和 `multivalue_metrics`，但不调用 `validate_gold_record`，报告固定写入：

```json
{"evidence_level": "construction_truth_only", "formal_gold": false, "threshold_claim": null}
```

- [ ] **Step 6: 运行专项测试并提交**

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_frozen_contract_dataset.py -q`

Expected: PASS，篡改被拒绝且预评测不产生正式达标结论。

```powershell
git add -- backend/evaluation/datasets/frozen_contracts_v1 backend/tests/test_frozen_contract_dataset.py
git commit -m "feat: validate and precheck frozen contract corpus"
```

### Task 7: 生成 v1 冻结集并执行离线验收

**Files:**
- Generate ignored files: `a03-contract-audit/outputs/frozen-contracts-v1/`
- Update: `.planning/frozen-contracts-v1/progress.md`

- [ ] **Step 1: 运行全部数据集专项测试**

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_frozen_contract_dataset.py -q`

Expected: 全部 PASS。

- [ ] **Step 2: 生成一次冻结输出**

Run: `backend/.venv/Scripts/python.exe -m evaluation.datasets.frozen_contracts_v1.generate --output outputs/frozen-contracts-v1`

Expected: 输出 `valid=50 invalid=2 supplemental=1`，并写入冻结 manifest。

- [ ] **Step 3: 执行静态验证**

Run: `backend/.venv/Scripts/python.exe -m evaluation.datasets.frozen_contracts_v1.validate --dataset outputs/frozen-contracts-v1`

Expected: 数量、哈希、格式、画像、隐私和相似度全部通过；若失败，记录结果但不改冻结文件。

- [ ] **Step 4: 执行生产解析和 OCR**

Run: `backend/.venv/Scripts/python.exe -m evaluation.datasets.frozen_contracts_v1.build_predictions --dataset outputs/frozen-contracts-v1`

Expected: 生成 50 条预测和逐文件解析元数据；失败案例保留错误类型，不丢失分母。

- [ ] **Step 5: 执行构造真值技术预评测**

Run: `backend/.venv/Scripts/python.exe -m evaluation.datasets.frozen_contracts_v1.precheck --dataset outputs/frozen-contracts-v1`

Expected: 输出真实得分，并明确 `construction_truth_only`、`formal_gold=false`。

### Task 8: 环境审计与真实 50+2 API 批测

**Files:**
- Generate ignored evidence: `a03-contract-audit/outputs/evaluation-runs/`
- Update: `.planning/frozen-contracts-v1/progress.md`

- [ ] **Step 1: 审计外部前置条件**

检查 `redis-server`/Docker、Celery worker、LLM 配置、端口 8000 和隔离数据库能力。不得输出密钥值，只记录是否配置。

- [ ] **Step 2: 条件齐全时启动隔离服务**

后端使用独立数据库和存储目录，Redis/Celery 使用验收队列。获取管理员测试令牌后设置临时进程环境变量 `A03_BATCH_TOKEN`，不写入文件。

- [ ] **Step 3: 执行现有批测 CLI**

Run:

```powershell
backend/.venv/Scripts/python.exe -m evaluation.cli batch --manifest outputs/frozen-contracts-v1/batch-manifest.json --base-url http://127.0.0.1:8000/api --token-env A03_BATCH_TOKEN --runs-root outputs/evaluation-runs
```

Expected: 50 个有效项全部 `done`、`failed=0`，两份异常文件分别 HTTP 400。若依赖缺失，CLI 或环境审计记录 `blocked`，不能改用 mock 结论。

- [ ] **Step 4: 执行 SX-001 补充失败隔离测试**

单独提交非空损坏 PDF，确认创建为 202、解析后 item 为 `failed`、重试计数递增且错误响应不泄露路径或堆栈。

- [ ] **Step 5: 停止本轮创建的服务进程**

仅停止并回收本轮启动的进程，不影响用户原有服务。

### Task 9: 文档、完整门禁与交付

**Files:**
- Modify: `a03-contract-audit/docs/evaluation/hard-indicator-matrix.md`
- Modify: `a03-contract-audit/PROGRESS.md`
- Modify: `a03-contract-audit/backend/evaluation/datasets/frozen_contracts_v1/README.md`
- Update: `.planning/frozen-contracts-v1/task_plan.md`
- Update: `.planning/frozen-contracts-v1/progress.md`

- [ ] **Step 1: 按真实结果更新证据口径**

只写已执行结果：静态/解析/预评测、API passed 或 blocked、数据集版本与 SHA-256。不得把 construction truth 预评测写成正式准确率达标。

- [ ] **Step 2: 运行数据集专项和相关回归**

Run:

```powershell
backend/.venv/Scripts/python.exe -m pytest backend/tests/test_frozen_contract_dataset.py backend/tests/test_evaluation_batch.py backend/tests/test_parser_contracts.py backend/tests/test_element_metrics.py -q
```

Expected: 零失败。

- [ ] **Step 3: 运行完整质量门禁**

Run: `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/quality_gate.ps1`

Expected: 评测、后端、前端、类型检查和生产构建全部退出码 0。

- [ ] **Step 4: 检查冻结输出与 Git 边界**

Run: `git status --short`

Expected: `outputs/frozen-contracts-v1/` 不出现在 Git 状态；源码、测试和文档改动清晰可审阅。

- [ ] **Step 5: 提交文档与最终状态**

```powershell
git add -- PROGRESS.md docs/evaluation/hard-indicator-matrix.md backend/evaluation/datasets/frozen_contracts_v1/README.md
git commit -m "docs: record frozen contract pre-acceptance evidence"
```

最终交付报告列出：生成文件数量与格式、冻结清单哈希、静态验证、解析/OCR结果、真实技术预评测分数、API 批测状态、未完成的双人复核和外部企业样本边界。
