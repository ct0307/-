# 合同上传与解析可靠性修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让特殊字体 PDF 稳定解析，并让单合同上传入口持续、准确地展示每份文件的上传与解析状态。

**Architecture:** 后端在 PDF 提取边界比较 `pdfplumber` 与 PyMuPDF 候选质量，日志只输出脱敏摘要，解析端点统一返回安全错误契约。前端用 Pinia 维护最小上传记录状态机，当前合同切换通过重新解析现有合同 ID 原子完成，不增加数据库表。

**Tech Stack:** Python、FastAPI、pytest、Vue 3、TypeScript、Pinia、Element Plus、Playwright。

---

### Task 1: PDF 候选质量与日志脱敏

**Files:**
- Modify: `backend/app/services/parser/extractor.py`
- Test: `backend/tests/test_parser_contracts.py`

- [ ] **Step 1: 写入失败测试**

新增测试覆盖：兼容部首达到阈值时采用更优 PyMuPDF 候选；较短或仍乱码的候选不替换；单个合法字符不触发回退；`extract_elements` 的日志参数不包含字段值。

```python
def test_pdf_prefers_clean_pymupdf_candidate_for_compatibility_radicals(monkeypatch):
    # pdfplumber 返回含多个康熙部首的文本，PyMuPDF 返回等长正常中文。
    result = extractor._extract_pdf_result(b"pdf")
    assert "甲方" in result.text
    assert "⾃" not in result.text

def test_elements_log_contains_keys_not_contract_values(monkeypatch):
    captured = {}
    monkeypatch.setattr(extractor.log, "info", lambda _event, **kw: captured.update(kw))
    extractor.extract_elements("甲方：敏感公司\n合同正文")
    assert "敏感公司" not in repr(captured)
```

- [ ] **Step 2: 运行测试并确认 RED**

Run: `python -m pytest tests/test_parser_contracts.py -q`

Expected: 新增测试因缺少候选质量选择和日志脱敏而失败。

- [ ] **Step 3: 最小实现**

在 `extractor.py` 增加小型纯函数：

```python
def _compatibility_radical_count(text: str) -> int: ...
def _has_suspicious_radicals(text: str) -> bool: ...
def _prefer_pymupdf_text(primary: str, alternate: str) -> bool: ...
def _normalize_compatibility_radicals(text: str) -> str: ...
```

触发范围限定为 U+2E80-U+2FDF；PyMuPDF 候选必须非空、长度达到 70%、兼容部首更少且 CJK 比例不下降。将 `parser.elements` 日志改为 `fields=[...]`、`field_count`、`text_length` 和布尔信号，不传字段值。

- [ ] **Step 4: 运行测试并确认 GREEN**

Run: `python -m pytest tests/test_parser_contracts.py -q`

Expected: 全部通过。

### Task 2: 日志编码与安全解析错误契约

**Files:**
- Modify: `backend/app/core/logging.py`
- Modify: `backend/app/api/v1/endpoints/contracts.py`
- Modify: `backend/app/schemas/contract.py`
- Test: `backend/tests/test_contract_quality_api.py`
- Create: `backend/tests/test_logging_encoding.py`

- [ ] **Step 1: 写入失败测试**

```python
def test_setup_logging_reconfigures_text_stream_with_safe_errors(monkeypatch):
    setup_logging()
    assert stream.encoding.lower() == "utf-8"
    assert stream.errors == "backslashreplace"

def test_parse_contract_maps_parser_exception_to_safe_error(monkeypatch, db_contract):
    monkeypatch.setattr(contracts, "extract_document", lambda _: (_ for _ in ()).throw(UnicodeError("C:/secret")))
    with pytest.raises(HTTPException) as exc:
        contracts.parse_contract(db_contract.id, db=db, user=user)
    assert exc.value.detail == {"code": "PDF_TEXT_ENCODING_ERROR", "detail": "PDF 文本编码异常，请重新导出 PDF 后重试"}
    assert "secret" not in repr(exc.value.detail)
```

- [ ] **Step 2: 运行测试并确认 RED**

Run: `python -m pytest tests/test_logging_encoding.py tests/test_contract_quality_api.py -q`

Expected: 错误结构和输出流防护尚不存在，测试失败。

- [ ] **Step 3: 最小实现**

为文本流使用 `reconfigure(encoding="utf-8", errors="backslashreplace")`，不支持 `reconfigure` 时保持原流并依赖脱敏日志避免业务异常。解析端点捕获解析器定义的可预期异常和未知异常，记录错误类型，不记录路径或原始消息；以 HTTP 422/503/500 返回 `{code, detail}`。成功响应不变。

- [ ] **Step 4: 运行测试并确认 GREEN**

Run: `python -m pytest tests/test_logging_encoding.py tests/test_contract_quality_api.py -q`

Expected: 全部通过。

### Task 3: 前端上传记录状态机

**Files:**
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/stores/audit-session.ts`
- Modify: `frontend/src/stores/auth.ts`
- Create: `frontend/tests/contract-upload-session.spec.ts`

- [ ] **Step 1: 写入失败的 Playwright 浏览器测试**

通过路由 mock 模拟上传成功/解析失败、手动重试成功和合同切换失败，断言页面状态，不引入新的测试依赖。

```typescript
await expect(page.getByText('上传成功，解析失败')).toBeVisible()
await expect(page.getByText('PDF 文本编码异常，请重新导出 PDF 后重试')).toBeVisible()
await page.getByRole('button', { name: '重新解析' }).click()
await expect(page.getByText('解析完成')).toBeVisible()
```

- [ ] **Step 2: 运行测试并确认 RED**

Run: `$env:E2E_BASE_URL='http://127.0.0.1:5173'; npm.cmd test -- tests/contract-upload-session.spec.ts`

Expected: 页面没有记录列表和重试入口，测试失败。

- [ ] **Step 3: 最小实现**

定义：

```typescript
type UploadStatus = 'uploading' | 'upload_failed' | 'parsing' | 'parse_failed' | 'parsed'
interface UploadRecord {
  localId: string
  filename: string
  contractId: number | null
  status: UploadStatus
  errorCode: string
  errorMessage: string
}
```

`uploadAndParse` 请求前创建记录；解析成功后才提交当前合同。增加 `retryParse(record)` 和 `selectParsedContract(record)`；切换先在局部变量获取解析响应，成功后一次性替换当前状态并清空风险、交叉验证和审查进度。API 拦截器从对象型 `detail` 提取 `code/detail`。`reset` 和 `logout` 清空记录。

- [ ] **Step 4: 运行测试并确认 GREEN**

Run: `$env:E2E_BASE_URL='http://127.0.0.1:5173'; npm.cmd test -- tests/contract-upload-session.spec.ts`

Expected: 全部通过。

### Task 4: 上传记录与错误交互界面

**Files:**
- Modify: `frontend/src/views/AuditView.vue`
- Test: `frontend/tests/contract-upload-session.spec.ts`
- Test: `frontend/tests/enterprise-ui.spec.ts`

- [ ] **Step 1: 扩展失败测试**

覆盖空记录、五种状态标签、持续错误、解析失败重试、已解析合同切换、忙碌禁用，以及 390x844/1440x900 下无横向溢出。

- [ ] **Step 2: 运行测试并确认 RED**

Run: `$env:E2E_BASE_URL='http://127.0.0.1:5173'; npm.cmd test -- tests/contract-upload-session.spec.ts`

Expected: 新 UI 行为缺失，测试失败。

- [ ] **Step 3: 最小实现**

在现有上传卡片内增加紧凑的“本次上传记录”列表，不嵌套卡片。每行展示文件名、状态和明确错误；使用图标按钮执行重试和切换并提供 tooltip。上传区绑定 `:disabled="session.busy"`。`onFile` 捕获 `unknown` 并显示安全的 `Error.message`，不再使用固定失败文案。

- [ ] **Step 4: 运行前端验证**

Run: `npm.cmd run type-check`

Run: `npm.cmd run build`

Run: `$env:E2E_BASE_URL='http://127.0.0.1:5173'; npm.cmd test -- tests/contract-upload-session.spec.ts tests/enterprise-ui.spec.ts`

Expected: 类型检查、构建和目标浏览器测试通过。

### Task 5: 真实文件与完整质量门禁

**Files:**
- No repository file changes expected.

- [ ] **Step 1: 在隔离数据库副本上验证三份真实 PDF**

使用真实文件调用解析器和 API 测试客户端，数据库指向临时副本；禁止重新写入当前真实开发库。断言三份均得到 `parsed`，劳务合同和离职保密协议不再抛编码异常。

- [ ] **Step 2: 浏览器验收**

通过 mock API 在 1440x900 和 390x844 检查正常、空、错误、重试和切换状态；控制台无错误或警告。真实开发服务只验证页面加载，不重新上传合同。

- [ ] **Step 3: 完整质量门禁**

Run: `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\quality_gate.ps1`

Expected: 所有门禁通过；任何环境性跳过必须单独报告，不能写成通过。

- [ ] **Step 4: 检查改动边界**

Run: `git status --short`

Run: `git diff --check`

Expected: 不含合同原件、数据库、日志、模型缓存或 `outputs/`。
