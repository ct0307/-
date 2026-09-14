# Contract Ingestion Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不重写现有 Vue/FastAPI 架构的前提下，让 50+2 合同集获得环境可复现、结果可诊断、失败可恢复、输出有证据且可持续回归的导入与解析能力。

**Architecture:** 保留 `ImportBatch -> ImportBatchItem -> Contract -> extract_document()` 主链路，在落库前新增独立内容预检，在异步解析边界新增稳定错误映射，并将分类与六要素输出升级为带证据的质量结果。未经验证的分类不自动就绪，OCR 和抽取低质量进入人工复核；冻结合同集通过独立验收命令接入统一质量门禁。

**Tech Stack:** Python 3.13、FastAPI、SQLAlchemy、Alembic、Celery、RapidOCR、ONNX Runtime、pytest、Vue 3、TypeScript、Pinia、Element Plus、Playwright。

---

## 文件结构

| 文件 | 责任 |
|---|---|
| `backend/app/services/imports/file_validation.py` | 可信文件类型识别、PDF/DOCX/TXT 同步结构预检 |
| `backend/app/services/imports/errors.py` | 解析异常到稳定错误码、中文说明、动作和重试性的唯一映射 |
| `backend/app/services/parser/readiness.py` | OCR 依赖与子进程自检，不接触真实合同 |
| `backend/app/services/imports/classifier.py` | 14 类候选评分、证据分区和保守置信度 |
| `backend/app/services/parser/elements.py` | 六要素候选、规范化、字段校验与原文锚点 |
| `backend/app/api/v1/endpoints/imports.py` | 在存储/建合同前调用预检，装配逐文件安全结果 |
| `backend/app/tasks/import_tasks.py` | 解析、质量状态、分类、证据持久化及失败映射 |
| `backend/app/main.py` | 在现有 `live/ready/preflight` 中增加 OCR 状态 |
| `backend/app/models/models.py`、`backend/app/db/init_db.py` | 新增要素证据 JSON 字段 |
| `backend/alembic/versions/20260914_02_contract_element_evidence.py` | PostgreSQL/SQLite 兼容的增量迁移与回滚 |
| `backend/evaluation/ingestion_reliability.py` | 50+2 解析、分类、要素和错误隔离的统一验收 |
| `scripts/quality_gate.py`、`scripts/quality_gate.ps1` | 可选接收冻结集目录并运行真实合同集门禁 |
| `frontend/src/api/imports.ts`、`frontend/src/api/types.ts` | 对齐错误动作、重试性和要素证据响应类型 |
| `frontend/src/utils/import-errors.ts` | 错误码到用户操作提示的前端兜底映射 |
| `frontend/src/components/audit/ContractInbox.vue` | 逐文件错误动作、OCR 复核和分类确认反馈 |

## Task 1: 受控重建 Python 环境并验证真实 OCR

**Files:**
- Create after audit: `a03-contract-audit/backend/requirements-dev.txt`
- Modify after audit: `a03-contract-audit/docs/evaluation/ocr-dependency-audit.md`
- Create after audit: `a03-contract-audit/docs/evaluation/python-wheel-manifest.json`
- Runtime-only, do not commit: `a03-contract-audit/backend/.venv/`
- Runtime-only, do not commit: `a03-contract-audit/backend/.venv-broken-20260914/`
- Runtime-only, do not commit: `a03-contract-audit/outputs/wheelhouse/`

- [ ] **Step 1: 在安装或移动目录前暂停并取得明确授权**

向用户说明将从 PyPI 获取 `requirements.txt` 中固定版本及传递依赖，并补充仅用于测试的 `pytest==8.3.5`。重点包为 Apache-2.0 的 RapidOCR 3.9.2 和 MIT 的 ONNX Runtime 1.28.0；说明当前审计时点、wheel SHA-256、许可证和公开漏洞记录。未经明确同意，不运行下载、安装、旧环境移动或新环境创建命令。

- [ ] **Step 2: 写明开发测试依赖并下载可审计 wheelhouse**

```text
-r requirements.txt
pytest==8.3.5
```

Run after approval:

```powershell
Set-Location a03-contract-audit/backend
py -3.13 -m pip download --dest ..\outputs\wheelhouse -r requirements-dev.txt
```

Expected: 下载命令退出 0。对 wheelhouse 中每个文件计算 SHA-256，生成不含本机绝对路径的 `python-wheel-manifest.json`，记录包名、版本、文件名、哈希、许可证证据、公开漏洞检查结果和审计日期。

- [ ] **Step 3: 保留旧环境并在最终路径重建**

先确认没有 API 或 Celery 进程使用旧解释器，并确认 `.venv-broken-20260914` 不存在。将旧 `.venv` 移动到 `.venv-broken-20260914`，然后直接在最终 `.venv` 路径创建环境；禁止把已创建的 venv 改名，因为 Windows 启动器和 `pyvenv.cfg` 可能保留绝对路径。

```powershell
Set-Location a03-contract-audit/backend
Move-Item -LiteralPath .venv -Destination .venv-broken-20260914
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --no-index --find-links ..\outputs\wheelhouse -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pip check
```

Expected: 所有命令退出 0，`pyvenv.cfg` 中不存在乱码路径，旧环境仍可恢复。若任一命令失败，保留失败现场并将旧目录移回 `.venv`，不删除任何环境目录。

- [ ] **Step 4: 验证中文路径、真实引擎和 OCR 子进程**

```powershell
Set-Location a03-contract-audit/backend
.\.venv\Scripts\python.exe -c "import rapidocr, onnxruntime; print(rapidocr.__version__, onnxruntime.__version__)"
.\.venv\Scripts\python.exe -m pytest tests/test_ocr_real_integration.py tests/test_ocr_process.py -q
```

Expected: RapidOCR 与 ONNX Runtime 版本正确，真实 OCR 集成测试不是 skip，OCR 子进程测试通过。严格 readiness 自检在 Task 5 创建对应模块后再验收。

- [ ] **Step 5: 更新供应链证据并提交**

只写实测事实：解释器版本、平台、每个 wheel 的 SHA-256、许可证、公开漏洞检查、`pip check` 和真实 OCR 冒烟结果；不得沿用旧环境结论。旧 `.venv-broken-20260914` 是否删除由用户在项目验收后另行决定。

```powershell
git add a03-contract-audit/backend/requirements-dev.txt a03-contract-audit/docs/evaluation/ocr-dependency-audit.md a03-contract-audit/docs/evaluation/python-wheel-manifest.json
git commit -m "build: make OCR development runtime reproducible"
```

## Task 2: 建立可信文件内容预检

**Files:**
- Create: `a03-contract-audit/backend/app/services/imports/file_validation.py`
- Create: `a03-contract-audit/backend/tests/test_import_file_validation.py`

- [ ] **Step 1: 写失败测试，覆盖 PDF、DOCX、TXT 和伪装格式**

```python
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import fitz
import pytest

from app.services.imports.file_validation import FileValidationError, validate_upload


def pdf_bytes() -> bytes:
    document = fitz.open()
    document.new_page()
    data = document.tobytes()
    document.close()
    return data


def docx_bytes(*, include_document: bool = True) -> bytes:
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        if include_document:
            archive.writestr("word/document.xml", "<w:document/>")
    return output.getvalue()


def test_rejects_nonempty_corrupt_pdf():
    with pytest.raises(FileValidationError) as raised:
        validate_upload("broken.pdf", b"%PDF-1.7\nnot-a-document")
    assert raised.value.code == "PDF_CORRUPT"


def test_rejects_extension_content_mismatch():
    with pytest.raises(FileValidationError) as raised:
        validate_upload("masked.pdf", docx_bytes())
    assert raised.value.code == "FILE_TYPE_MISMATCH"


def test_rejects_docx_without_main_document():
    with pytest.raises(FileValidationError) as raised:
        validate_upload("broken.docx", docx_bytes(include_document=False))
    assert raised.value.code == "DOCX_STRUCTURE_INVALID"


def test_accepts_supported_documents():
    assert validate_upload("ok.pdf", pdf_bytes()).extension == ".pdf"
    assert validate_upload("ok.docx", docx_bytes()).extension == ".docx"
    assert validate_upload("ok.txt", "合同正文".encode()).text_encoding == "utf-8"
```

- [ ] **Step 2: 运行测试并确认红灯**

Run: `Set-Location a03-contract-audit/backend; .\.venv\Scripts\python.exe -m pytest tests/test_import_file_validation.py -q`

Expected: FAIL，提示 `app.services.imports.file_validation` 不存在。

- [ ] **Step 3: 实现格式化错误和结构化预检**

```python
from dataclasses import dataclass
from io import BytesIO
import os
from zipfile import BadZipFile, ZipFile


@dataclass(frozen=True)
class ValidatedUpload:
    extension: str
    text_encoding: str | None = None


class FileValidationError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def validate_upload(filename: str, content: bytes) -> ValidatedUpload:
    extension = os.path.splitext(os.path.basename(filename))[1].lower()
    if extension not in {".pdf", ".docx", ".txt"}:
        raise FileValidationError("UNSUPPORTED_FILE_TYPE", "不支持的文件类型")
    if not content:
        raise FileValidationError("EMPTY_FILE", "文件为空")
    if extension == ".pdf":
        if not content.startswith(b"%PDF-"):
            raise FileValidationError("FILE_TYPE_MISMATCH", "文件内容与 PDF 扩展名不一致")
        return _validate_pdf(content)
    if extension == ".docx":
        if not content.startswith(b"PK"):
            raise FileValidationError("FILE_TYPE_MISMATCH", "文件内容与 DOCX 扩展名不一致")
        return _validate_docx(content)
    return _validate_text(content)
```

`_validate_pdf()` 使用 `fitz.open(stream=content, filetype="pdf")`，拒绝 `needs_pass`、`page_count < 1` 和打开异常，并在 `finally` 关闭文档。`_validate_docx()` 使用 `ZipFile`、`testzip()` 和 `PurePosixPath`，拒绝损坏成员、绝对路径、`..`、缺失 `[Content_Types].xml` 或 `word/document.xml`。`_validate_text()` 依次严格尝试 `utf-8-sig`、`gb18030`，拒绝 NUL 字节和解码后空文本。

- [ ] **Step 4: 运行预检测试并确认绿灯**

Run: `Set-Location a03-contract-audit/backend; .\.venv\Scripts\python.exe -m pytest tests/test_import_file_validation.py -q`

Expected: PASS，全部预检用例通过。

- [ ] **Step 5: 提交本任务**

```powershell
git add a03-contract-audit/backend/app/services/imports/file_validation.py a03-contract-audit/backend/tests/test_import_file_validation.py
git commit -m "feat: validate contract file contents before import"
```

## Task 3: 在所有上传入口落实“失败不建合同”

**Files:**
- Modify: `a03-contract-audit/backend/app/api/v1/endpoints/imports.py:40-154`
- Modify: `a03-contract-audit/backend/app/api/v1/endpoints/contracts.py:42-43, 193-345`
- Modify: `a03-contract-audit/backend/tests/test_import_api.py`
- Modify: `a03-contract-audit/backend/tests/test_contract_quality_api.py`

- [ ] **Step 1: 写失败测试锁定数据后果**

```python
def test_corrupt_pdf_is_rejected_before_contract_creation(db, legal_user, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "STORAGE_DIR", str(tmp_path))
    response = create_import(
        files=[upload("broken.pdf", b"%PDF-1.7\ninvalid")],
        idempotency_key="corrupt-pdf-request",
        department="法务部",
        db=db,
        user=legal_user,
    )
    item = response.items[0]
    assert item.status == "failed"
    assert item.error_code == "PDF_CORRUPT"
    assert item.contract_id is None
    assert db.query(Contract).count() == 0
    assert list(tmp_path.iterdir()) == []
```

同时给 `/contracts/upload` 和 `/contracts/batch-upload` 增加同样断言，避免旧入口绕过可信边界。

- [ ] **Step 2: 运行三个入口的测试并确认红灯**

Run: `Set-Location a03-contract-audit/backend; .\.venv\Scripts\python.exe -m pytest tests/test_import_api.py tests/test_contract_quality_api.py -q`

Expected: FAIL，非空损坏 PDF 仍创建 `Contract` 或进入 `queued`。

- [ ] **Step 3: 在读到字节后、写文件前调用统一预检**

```python
from app.services.imports.file_validation import FileValidationError, validate_upload


def _validation_failure(upload: PreparedUpload, exc: FileValidationError) -> ImportBatchItem:
    return ImportBatchItem(
        filename=upload.filename,
        status="failed",
        error_code=exc.code,
        error_message=exc.message,
    )


# _append_prepared_uploads 循环内
try:
    validate_upload(upload.filename, content)
except FileValidationError as exc:
    item = _validation_failure(upload, exc)
else:
    stored_path = os.path.join(
        settings.storage_path,
        f"{uuid.uuid4().hex}{upload.extension}",
    )
    with open(stored_path, "wb") as stream:
        stream.write(encrypt_bytes(content))
    created_paths.append(stored_path)
    contract = Contract(
        filename=upload.filename,
        storage_path=stored_path,
        contract_type="",
        department=department,
        status="uploaded",
        uploaded_by=batch.owner_id,
        upload_idempotency_key=hashlib.sha256(
            f"{operation_key}:{index}".encode()
        ).hexdigest(),
        content_sha256=upload.content_sha256,
    )
    item = ImportBatchItem(
        filename=upload.filename,
        contract=contract,
        status="queued",
    )
```

单合同入口把 `FileValidationError` 映射为 HTTP 400/413/422；批量旧入口逐文件返回 `error_code`。保留现有幂等指纹，预检失败项可以保留在 `ImportBatchItem`，但 `contract_id` 必须为空。

- [ ] **Step 4: 运行上传回归测试**

Run: `Set-Location a03-contract-audit/backend; .\.venv\Scripts\python.exe -m pytest tests/test_import_api.py tests/test_contract_quality_api.py tests/test_import_models.py -q`

Expected: PASS，三个入口均无法为损坏输入创建合同。

- [ ] **Step 5: 提交本任务**

```powershell
git add a03-contract-audit/backend/app/api/v1/endpoints/imports.py a03-contract-audit/backend/app/api/v1/endpoints/contracts.py a03-contract-audit/backend/tests/test_import_api.py a03-contract-audit/backend/tests/test_contract_quality_api.py
git commit -m "fix: reject malformed contracts before persistence"
```

## Task 4: 统一解析错误模型并保留根因类别

**Files:**
- Create: `a03-contract-audit/backend/app/services/imports/errors.py`
- Create: `a03-contract-audit/backend/tests/test_import_errors.py`
- Modify: `a03-contract-audit/backend/app/tasks/import_tasks.py:24-70`
- Modify: `a03-contract-audit/backend/app/api/v1/endpoints/contracts.py:48-94`
- Modify: `a03-contract-audit/backend/app/schemas/import_batch.py:21-33`
- Modify: `a03-contract-audit/backend/tests/test_import_tasks.py`

- [ ] **Step 1: 写异常分类失败测试**

```python
import pytest

from app.services.imports.errors import parse_failure
from app.services.parser.ocr import OCRError, OCRLimitExceeded, OCRTimeout, OCRUnavailable


@pytest.mark.parametrize(
    ("exception", "code", "retryable"),
    [
        (OCRUnavailable("path and model detail"), "OCR_UNAVAILABLE", True),
        (OCRTimeout("slow"), "OCR_TIMEOUT", True),
        (OCRLimitExceeded("large"), "OCR_LIMIT_EXCEEDED", False),
        (OCRError("bad protocol"), "OCR_PROTOCOL_ERROR", True),
        (RuntimeError("secret C:/private/file.pdf"), "PARSE_INTERNAL_ERROR", True),
    ],
)
def test_parse_failure_is_stable_and_redacted(exception, code, retryable):
    failure = parse_failure(exception)
    assert failure.code == code
    assert failure.retryable is retryable
    assert "private" not in failure.message
    assert failure.action
```

- [ ] **Step 2: 运行测试并确认红灯**

Run: `Set-Location a03-contract-audit/backend; .\.venv\Scripts\python.exe -m pytest tests/test_import_errors.py tests/test_import_tasks.py -q`

Expected: FAIL，错误模块不存在且任务仍统一写 `PARSE_FAILED`。

- [ ] **Step 3: 实现唯一错误目录**

```python
from dataclasses import dataclass

from app.services.parser.ocr import OCRError, OCRLimitExceeded, OCRTimeout, OCRUnavailable


@dataclass(frozen=True)
class ImportFailure:
    code: str
    message: str
    action: str
    retryable: bool
    http_status: int


def parse_failure(exc: Exception) -> ImportFailure:
    if isinstance(exc, OCRUnavailable):
        return ImportFailure("OCR_UNAVAILABLE", "扫描件识别服务未就绪", "联系管理员修复服务后重新解析", True, 503)
    if isinstance(exc, OCRTimeout):
        return ImportFailure("OCR_TIMEOUT", "扫描件识别超时", "稍后重新解析；持续超时请拆分文件", True, 503)
    if isinstance(exc, OCRLimitExceeded):
        return ImportFailure("OCR_LIMIT_EXCEEDED", "文件超过扫描识别资源限制", "拆分或压缩文件后重新上传", False, 422)
    if isinstance(exc, OCRError):
        return ImportFailure("OCR_PROTOCOL_ERROR", "扫描件识别结果无效", "重新解析；持续失败请联系管理员", True, 503)
    return ImportFailure("PARSE_INTERNAL_ERROR", "合同解析失败", "稍后重新解析", True, 500)
```

`contracts.py` 和 `import_tasks.py` 必须共同调用该函数。`ImportItemOut` 新增 `error_action: str | None`、`retryable: bool`、`correlation_id: str | None`，其中关联 ID 使用 `import-item:{item.id}`，不新增数据库列。

- [ ] **Step 4: 证明任务保留根因且不泄密**

Run: `Set-Location a03-contract-audit/backend; .\.venv\Scripts\python.exe -m pytest tests/test_import_errors.py tests/test_import_tasks.py tests/test_contract_quality_api.py -q`

Expected: PASS；`OCRUnavailable` 写为 `OCR_UNAVAILABLE`，异常原文和文件绝对路径不进入 API。

- [ ] **Step 5: 提交本任务**

```powershell
git add a03-contract-audit/backend/app/services/imports/errors.py a03-contract-audit/backend/app/tasks/import_tasks.py a03-contract-audit/backend/app/api/v1/endpoints/contracts.py a03-contract-audit/backend/app/schemas/import_batch.py a03-contract-audit/backend/tests/test_import_errors.py a03-contract-audit/backend/tests/test_import_tasks.py a03-contract-audit/backend/tests/test_contract_quality_api.py
git commit -m "feat: expose stable contract parsing failures"
```

## Task 5: 增加 OCR 就绪与严格预检

**Files:**
- Create: `a03-contract-audit/backend/app/services/parser/readiness.py`
- Create: `a03-contract-audit/backend/tests/test_ocr_readiness.py`
- Modify: `a03-contract-audit/backend/app/services/parser/ocr_worker.py`
- Modify: `a03-contract-audit/backend/app/main.py:74-114`
- Modify: `a03-contract-audit/backend/tests/test_health_endpoints.py`

- [ ] **Step 1: 写健康检查失败测试**

```python
def test_ready_reports_ocr_degraded_without_rejecting_traffic(monkeypatch):
    monkeypatch.setattr("app.main.collect_database_readiness", lambda: {"ready": True})
    monkeypatch.setattr("app.main.collect_model_readiness", lambda **_: {"ready": True})
    monkeypatch.setattr(
        "app.main.probe_ocr_runtime",
        lambda strict=False: {"ready": False, "error_code": "ocr_unavailable"},
    )
    response = client.get("/health/ready")
    assert response.status_code == 200
    assert response.json()["checks"]["ocr"]["ready"] is False


def test_preflight_requires_real_ocr_self_test(monkeypatch):
    monkeypatch.setattr(
        "app.main.probe_ocr_runtime",
        lambda strict=False: {"ready": not strict, "error_code": "ocr_self_test_failed" if strict else None},
    )
    response = client.get("/health/preflight")
    assert response.status_code == 503
```

- [ ] **Step 2: 运行健康检查并确认红灯**

Run: `Set-Location a03-contract-audit/backend; .\.venv\Scripts\python.exe -m pytest tests/test_ocr_readiness.py tests/test_health_endpoints.py -q`

Expected: FAIL，响应中没有 `ocr` 检查项。

- [ ] **Step 3: 实现浅检查与严格子进程自检**

`probe_ocr_runtime(strict=False)` 使用 `importlib.util.find_spec()` 检查 `rapidocr`、`onnxruntime`；严格模式以固定 20 秒超时启动 `python -m app.services.parser.ocr_worker --self-test`。自检在内存中用 PyMuPDF 生成含 `CONTRACT 10000` 的单页图片，直接调用 `RapidOCREngine.recognize()`，只输出协议版本、成功布尔值和耗时，不输出图像。

为便于独立测试，将 `collect_readiness()` 现有数据库和模型逻辑原样提取为 `collect_database_readiness()`、`collect_model_readiness(refresh: bool)` 两个内部函数；不改变既有错误码或模型探活行为。上方测试只替换这两个新边界和 `probe_ocr_runtime()`。

```python
@dataclass(frozen=True)
class OCRReadiness:
    ready: bool
    error_code: str | None = None
    detail: str | None = None


def probe_ocr_runtime(*, strict: bool = False) -> OCRReadiness:
    missing = [name for name in ("rapidocr", "onnxruntime") if find_spec(name) is None]
    if missing:
        return OCRReadiness(False, "ocr_unavailable", "OCR 依赖未安装")
    if not strict:
        return OCRReadiness(True)
    return _run_worker_self_test(timeout_seconds=20.0)
```

`/health/ready` 仍只以数据库为硬门槛；`/health/preflight` 对数据库、模型和 OCR 全部执行 `all(check.ready)`。

- [ ] **Step 4: 运行 OCR 与健康检查回归**

Run: `Set-Location a03-contract-audit/backend; .\.venv\Scripts\python.exe -m pytest tests/test_ocr_readiness.py tests/test_health_endpoints.py tests/test_ocr_process.py -q`

Expected: PASS，缺失依赖被稳定报告，严格模式失败返回 503，普通 ready 保持 200。

- [ ] **Step 5: 提交本任务**

```powershell
git add a03-contract-audit/backend/app/services/parser/readiness.py a03-contract-audit/backend/app/services/parser/ocr_worker.py a03-contract-audit/backend/app/main.py a03-contract-audit/backend/tests/test_ocr_readiness.py a03-contract-audit/backend/tests/test_health_endpoints.py
git commit -m "feat: report OCR runtime readiness"
```

## Task 6: 修复分类覆盖并关闭未经校准的自动就绪

**Files:**
- Modify: `a03-contract-audit/backend/app/core/config.py:49-52`
- Modify: `a03-contract-audit/backend/.env.example`
- Modify: `a03-contract-audit/backend/app/services/imports/classifier.py`
- Modify: `a03-contract-audit/backend/app/services/imports/service.py:20-31`
- Modify: `a03-contract-audit/backend/app/tasks/import_tasks.py:38-63`
- Modify: `a03-contract-audit/backend/tests/test_contract_type_classifier.py`
- Modify: `a03-contract-audit/backend/tests/test_import_service.py`
- Modify: `a03-contract-audit/backend/tests/test_import_tasks.py`

- [ ] **Step 1: 写通用保密条款、14 类候选和安全阈值测试**

```python
ALL_TYPES = [
    "软件开发外包合同", "技术服务合同", "采购合同", "销售合同",
    "劳动合同", "租赁合同", "保密协议", "合作协议", "服务协议",
    "框架协议", "技术开发合同", "合作合同", "服务合同", "劳务合同",
]


def test_generic_confidentiality_clause_cannot_override_title():
    result = classify_contract_type(
        filename="设备采购合同.pdf",
        text="设备采购合同\n甲方采购服务器。双方承担保密义务并保护商业秘密。",
        available_types=ALL_TYPES,
    )
    assert result.suggested_type == "采购合同"
    assert "保密协议" not in [candidate.contract_type for candidate in result.candidates[:1]]


def test_every_configured_type_can_appear_in_ranked_candidates():
    for contract_type in ALL_TYPES:
        result = classify_contract_type(
            filename=f"{contract_type}.pdf",
            text=f"{contract_type}\n双方订立本合同。",
            available_types=ALL_TYPES,
        )
        assert contract_type in [candidate.contract_type for candidate in result.candidates]


def test_auto_ready_is_disabled_until_calibrated(monkeypatch):
    monkeypatch.setattr(settings, "CONTRACT_TYPE_AUTO_READY_ENABLED", False)
    assert target_status("采购合同", 0.99) == "awaiting_confirmation"
```

- [ ] **Step 2: 运行分类与状态测试并确认红灯**

Run: `Set-Location a03-contract-audit/backend; .\.venv\Scripts\python.exe -m pytest tests/test_contract_type_classifier.py tests/test_import_service.py tests/test_import_tasks.py -q`

Expected: FAIL，保密关键词压过主交易类型、九类不可达且 0.85 自动就绪。

- [ ] **Step 3: 实现分区加权候选**

```python
@dataclass(frozen=True)
class TypeCandidate:
    contract_type: str
    score: float
    evidence: tuple[str, ...]


@dataclass(frozen=True)
class TypeSuggestion:
    suggested_type: str
    confidence: float
    evidence: list[str]
    candidates: tuple[TypeCandidate, ...] = ()
    auto_ready_eligible: bool = False


def classify_contract_type(*, filename: str, text: str, available_types: list[str]) -> TypeSuggestion:
    title = _title_material(filename, text)
    lead = text[:1800]
    body = text[1800:8000]
    candidates = tuple(sorted(
        (_score_type(value, title=title, lead=lead, body=body) for value in available_types),
        key=lambda item: (-item.score, item.contract_type),
    ))
    best = candidates[0] if candidates and candidates[0].score > 0 else None
    confidence = _conservative_confidence(best, candidates[1] if len(candidates) > 1 else None)
    return TypeSuggestion(
        suggested_type=best.contract_type if best else "",
        confidence=confidence,
        evidence=list(best.evidence) if best else [],
        candidates=candidates[:3],
        auto_ready_eligible=bool(best and _has_primary_transaction_evidence(best)),
    )
```

标题/文件名权重为 6，首部主交易信号为 3，正文主交易信号为 1；保密、违约和争议解决通用条款权重不得超过 0.25。配置增加 `CONTRACT_TYPE_AUTO_READY_ENABLED: bool = False`，`target_status()` 只有在开关开启、置信度达到阈值且 `auto_ready_eligible=True` 时返回 `ready`。

```python
def target_status(
    suggested_type: str,
    confidence: float,
    *,
    auto_ready_eligible: bool = False,
    requires_review: bool = False,
    current_status: str = "parsing",
    retry: bool = False,
) -> str:
    if retry and current_status != "failed":
        raise ImportConflict("仅失败导入项可以重试")
    if requires_review:
        return "awaiting_confirmation"
    if (
        settings.CONTRACT_TYPE_AUTO_READY_ENABLED
        and auto_ready_eligible
        and suggested_type
        and confidence >= settings.CONTRACT_TYPE_READY_THRESHOLD
    ):
        return "ready"
    return "awaiting_confirmation"
```

`parse_import_item()` 必须把 `suggestion.auto_ready_eligible` 和 `parsed.requires_review` 显式传给 `target_status()`，避免未来调用方遗漏资格条件后意外放行。测试增加 `target_status("采购合同", 0.99, auto_ready_eligible=True, requires_review=True) == "awaiting_confirmation"`。

- [ ] **Step 4: 运行分类与导入任务测试**

Run: `Set-Location a03-contract-audit/backend; .\.venv\Scripts\python.exe -m pytest tests/test_contract_type_classifier.py tests/test_import_service.py tests/test_import_tasks.py -q`

Expected: PASS，默认所有建议进入 `awaiting_confirmation`，既有 90% 保密误判不再自动就绪。

- [ ] **Step 5: 提交本任务**

```powershell
git add a03-contract-audit/backend/app/core/config.py a03-contract-audit/backend/.env.example a03-contract-audit/backend/app/services/imports/classifier.py a03-contract-audit/backend/app/services/imports/service.py a03-contract-audit/backend/app/tasks/import_tasks.py a03-contract-audit/backend/tests/test_contract_type_classifier.py a03-contract-audit/backend/tests/test_import_service.py a03-contract-audit/backend/tests/test_import_tasks.py
git commit -m "fix: calibrate contract type readiness conservatively"
```

## Task 7: 建立六要素候选、校验与证据模型

**Files:**
- Create: `a03-contract-audit/backend/app/services/parser/elements.py`
- Create: `a03-contract-audit/backend/tests/test_element_extraction.py`
- Modify: `a03-contract-audit/backend/app/services/parser/extractor.py:506-633`
- Modify: `a03-contract-audit/backend/app/tasks/import_tasks.py`
- Modify: `a03-contract-audit/backend/app/api/v1/endpoints/contracts.py`
- Modify: `a03-contract-audit/backend/app/schemas/contract.py:133-159`

- [ ] **Step 1: 写字段证据和冲突校验测试**

```python
from app.services.parser.elements import extract_element_result
from app.services.parser.extractor import DocumentBlock, DocumentParseResult, SourceAnchor


def parsed(text: str, page: int = 1) -> DocumentParseResult:
    return DocumentParseResult(
        text=text,
        source="native",
        blocks=(DocumentBlock("p1", "page_text", text, SourceAnchor(page_number=page)),),
    )


def test_extracts_parties_amount_duration_and_evidence():
    result = extract_element_result(parsed(
        "甲方：之江科技有限公司\n乙方：云栖设备有限公司\n"
        "合同总价为人民币1,286,000元。合同期限自2026年10月1日至2027年3月31日。"
    ))
    assert result.values["party_a"] == "之江科技有限公司"
    assert result.values["amount"] == "人民币1,286,000元"
    evidence = result.evidence["amount"]
    assert evidence.page == 1
    assert evidence.raw_text in result.source_text
    assert result.source_text[evidence.start:evidence.end] == evidence.raw_text


def test_does_not_treat_penalty_as_contract_amount():
    result = extract_element_result(parsed("违约方应支付违约金100万元，合同采用按订单结算。"))
    assert result.values["amount"] is None


def test_conflicting_party_candidates_require_review():
    result = extract_element_result(parsed("甲方：甲公司\n采购方：乙公司\n乙方：丙公司"))
    assert result.evidence["party_a"].validation == "ambiguous"
    assert "party_a" in result.review_fields
```

- [ ] **Step 2: 运行要素测试并确认红灯**

Run: `Set-Location a03-contract-audit/backend; .\.venv\Scripts\python.exe -m pytest tests/test_element_extraction.py tests/test_parser_contracts.py -q`

Expected: FAIL，`extract_element_result` 不存在。

- [ ] **Step 3: 实现字段级结果与兼容包装**

```python
@dataclass(frozen=True)
class ElementEvidence:
    raw_text: str
    page: int | None
    start: int
    end: int
    confidence: float
    source: Literal["rule", "llm"]
    validation: Literal["valid", "ambiguous", "invalid"]


@dataclass(frozen=True)
class ElementResult:
    values: dict[str, str | list[str] | None]
    evidence: dict[str, ElementEvidence | list[ElementEvidence]]
    review_fields: tuple[str, ...]
    source_text: str


def extract_element_result(parsed: DocumentParseResult) -> ElementResult:
    candidates = _collect_candidates(parsed)
    selected = {
        "party_a": _select_party(candidates["party_a"]),
        "party_b": _select_party(candidates["party_b"]),
        "subject": _select_subject(candidates["subject"]),
        "amount": _select_total_amount(candidates["amount"]),
        "duration": _select_duration(candidates["duration"]),
        "payment_terms": _select_payment_terms(candidates["payment_terms"]),
    }
    return _build_result(parsed, selected)
```

候选必须保存全文字符区间并通过 `DocumentBlock.anchor` 反查页码。金额候选排除“违约金、赔偿、保证金、注册资本、单价”；期限候选区分合同期限、交付期、质保期；主体候选覆盖甲乙方、采购/供应方、委托/受托方、出租/承租方；付款节点返回有序列表。`extract_elements(text)` 保留为旧调用方的扁平兼容包装，但导入任务和同步解析改用 `extract_element_result(parsed)`。

导入任务和同步解析必须把文档质量与字段冲突合并为合同质量状态；不能在 `apply_parse_quality()` 后无条件覆盖为 `parsed`：

```python
element_result = extract_element_result(parsed)
review_reasons = [reason for reason in (parsed.review_reason,) if reason]
if element_result.review_fields:
    review_reasons.append("关键要素存在冲突，请人工确认")
contract.requires_review = bool(review_reasons)
contract.review_reason = "；".join(review_reasons) or None
contract.status = "review_required" if contract.requires_review else "parsed"
```

- [ ] **Step 4: 运行解析和日志脱敏回归**

Run: `Set-Location a03-contract-audit/backend; .\.venv\Scripts\python.exe -m pytest tests/test_element_extraction.py tests/test_parser_contracts.py tests/test_logging_encoding.py -q`

Expected: PASS，所有非空字段均有可定位证据，日志仍不包含字段值。

- [ ] **Step 5: 提交本任务**

```powershell
git add a03-contract-audit/backend/app/services/parser/elements.py a03-contract-audit/backend/app/services/parser/extractor.py a03-contract-audit/backend/app/tasks/import_tasks.py a03-contract-audit/backend/app/api/v1/endpoints/contracts.py a03-contract-audit/backend/app/schemas/contract.py a03-contract-audit/backend/tests/test_element_extraction.py a03-contract-audit/backend/tests/test_parser_contracts.py
git commit -m "feat: extract contract elements with source evidence"
```

## Task 8: 持久化证据并兼容现有 API

**Files:**
- Create: `a03-contract-audit/backend/alembic/versions/20260914_02_contract_element_evidence.py`
- Modify: `a03-contract-audit/backend/app/models/models.py:36-77`
- Modify: `a03-contract-audit/backend/app/db/init_db.py:60-80`
- Modify: `a03-contract-audit/backend/app/schemas/contract.py:133-159`
- Modify: `a03-contract-audit/backend/app/tasks/import_tasks.py`
- Modify: `a03-contract-audit/backend/app/api/v1/endpoints/contracts.py`
- Create: `a03-contract-audit/backend/tests/test_element_evidence_persistence.py`

- [ ] **Step 1: 写迁移和 API 兼容失败测试**

```python
def test_parse_response_keeps_flat_values_and_adds_evidence(client, uploaded_contract):
    response = client.post(f"/api/v1/contracts/{uploaded_contract.id}/parse")
    payload = response.json()
    assert isinstance(payload["elements"]["party_a"], (str, type(None)))
    assert payload["element_evidence"]["party_a"]["raw_text"]
    assert payload["element_evidence"]["party_a"]["start"] >= 0


def test_contract_persists_element_evidence(db, parsed_contract):
    stored = json.loads(parsed_contract.element_evidence_json)
    assert stored["schema_version"] == 1
    assert stored["fields"]["amount"]["validation"] in {"valid", "ambiguous", "invalid"}
```

- [ ] **Step 2: 运行持久化测试并确认红灯**

Run: `Set-Location a03-contract-audit/backend; .\.venv\Scripts\python.exe -m pytest tests/test_element_evidence_persistence.py -q`

Expected: FAIL，模型和响应尚无 `element_evidence`。

- [ ] **Step 3: 增加单列迁移和 Pydantic 响应**

```python
revision = "20260914_02"
down_revision = "20260914_01"


def upgrade() -> None:
    op.add_column(
        "contracts",
        sa.Column("element_evidence_json", sa.Text(), server_default="{}", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("contracts", "element_evidence_json")
```

ORM 同步增加 `element_evidence_json`；`ParseResponse` 增加 `element_evidence: dict = Field(default_factory=dict)`。`elements_json` 继续保存原有扁平值，证据列保存版本和字段证据，已有前端无需同时升级也能读取旧字段。

```python
from dataclasses import asdict


def evidence_to_json(value: ElementEvidence | list[ElementEvidence]) -> dict | list[dict]:
    if isinstance(value, list):
        return [asdict(item) for item in value]
    return asdict(value)


evidence_payload = {
    "schema_version": 1,
    "fields": {
        field: evidence_to_json(evidence)
        for field, evidence in result.evidence.items()
    },
    "review_fields": list(result.review_fields),
}
contract.element_evidence_json = json.dumps(evidence_payload, ensure_ascii=False)
```

- [ ] **Step 4: 验证空库升级、增量升级和回滚**

Run: `Set-Location a03-contract-audit/backend; .\.venv\Scripts\python.exe -m pytest tests/test_element_evidence_persistence.py tests/test_import_models.py tests/test_contract_quality_api.py -q`

Run: `Set-Location a03-contract-audit/backend; .\.venv\Scripts\python.exe -m alembic upgrade head`

Expected: 两条命令均退出 0，证据列存在，旧 `elements` 响应保持扁平。

- [ ] **Step 5: 提交本任务**

```powershell
git add a03-contract-audit/backend/alembic/versions/20260914_02_contract_element_evidence.py a03-contract-audit/backend/app/models/models.py a03-contract-audit/backend/app/db/init_db.py a03-contract-audit/backend/app/schemas/contract.py a03-contract-audit/backend/app/tasks/import_tasks.py a03-contract-audit/backend/app/api/v1/endpoints/contracts.py a03-contract-audit/backend/tests/test_element_evidence_persistence.py
git commit -m "feat: persist contract element evidence"
```

## Task 9: 前端展示可操作错误和人工复核状态

**Files:**
- Create: `a03-contract-audit/frontend/src/utils/import-errors.ts`
- Modify: `a03-contract-audit/frontend/src/api/imports.ts`
- Modify: `a03-contract-audit/frontend/src/api/types.ts`
- Modify: `a03-contract-audit/frontend/src/components/audit/ContractInbox.vue`
- Modify: `a03-contract-audit/frontend/tests/import-inbox-store.spec.ts`
- Modify: `a03-contract-audit/frontend/tests/contract-inbox-e2e.spec.ts`

- [ ] **Step 1: 写错误动作和移动端失败测试**

```typescript
test('shows actionable OCR and corrupt-file failures', async ({ page }) => {
  const fixture = batch([
    item({
      id: 3,
      status: 'failed',
      error_code: 'OCR_UNAVAILABLE',
      error_message: '扫描件识别服务未就绪',
      error_action: '联系管理员修复服务后重新解析',
      retryable: true,
    }),
    item({
      id: 4,
      contract_id: null,
      status: 'failed',
      error_code: 'PDF_CORRUPT',
      error_message: 'PDF 文件已损坏',
      error_action: '重新获取原文件后上传',
      retryable: false,
    }),
  ])
  await openAudit(page, fixture)
  await expect(page.getByText('联系管理员修复服务后重新解析')).toBeVisible()
  await expect(page.getByRole('button', { name: /重新解析.*扫描件/ })).toBeVisible()
  await expect(page.getByText('重新获取原文件后上传')).toBeVisible()
  await page.setViewportSize({ width: 390, height: 844 })
  expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(0)
})
```

- [ ] **Step 2: 运行前端测试并确认红灯**

Run: `Set-Location a03-contract-audit/frontend; npm.cmd test -- tests/import-inbox-store.spec.ts tests/contract-inbox-e2e.spec.ts`

Expected: FAIL，类型缺少 `error_action/retryable`，页面不展示动作。

- [ ] **Step 3: 增加类型和安全兜底映射**

```typescript
export interface ImportErrorMeta {
  message: string
  action: string
  retryable: boolean
}

const IMPORT_ERRORS: Record<string, ImportErrorMeta> = {
  PDF_CORRUPT: { message: 'PDF 文件已损坏', action: '重新获取原文件后上传', retryable: false },
  DOCX_CORRUPT: { message: 'Word 文件已损坏', action: '重新获取原文件后上传', retryable: false },
  OCR_UNAVAILABLE: { message: '扫描件识别服务未就绪', action: '联系管理员修复服务后重新解析', retryable: true },
  OCR_TIMEOUT: { message: '扫描件识别超时', action: '稍后重试，持续超时请拆分文件', retryable: true },
}

export function importErrorMeta(item: ImportItem): ImportErrorMeta {
  const fallback = IMPORT_ERRORS[item.error_code ?? '']
  return {
    message: item.error_message || fallback?.message || '文件处理失败',
    action: item.error_action || fallback?.action || '请稍后重试',
    retryable: item.retryable ?? fallback?.retryable ?? false,
  }
}
```

组件把错误说明和操作建议放在对应文件行内；只有 `contract_id` 存在且 `retryable=true` 时显示重新解析；低 OCR 置信度显示“需人工复核”和百分比，不与技术失败混淆。

- [ ] **Step 4: 运行前端单测、类型检查和构建**

Run: `Set-Location a03-contract-audit/frontend; npm.cmd test -- tests/import-inbox-store.spec.ts tests/contract-inbox-e2e.spec.ts tests/client-error.spec.ts`

Run: `Set-Location a03-contract-audit/frontend; npm.cmd run type-check; npm.cmd run build`

Expected: 所有命令退出 0，无 TypeScript 错误。

- [ ] **Step 5: 提交本任务**

```powershell
git add a03-contract-audit/frontend/src/utils/import-errors.ts a03-contract-audit/frontend/src/api/imports.ts a03-contract-audit/frontend/src/api/types.ts a03-contract-audit/frontend/src/components/audit/ContractInbox.vue a03-contract-audit/frontend/tests/import-inbox-store.spec.ts a03-contract-audit/frontend/tests/contract-inbox-e2e.spec.ts
git commit -m "feat: show actionable contract import failures"
```

## Task 10: 把 50+2 合同集接入可重复质量门禁

**Files:**
- Create: `a03-contract-audit/backend/evaluation/ingestion_reliability.py`
- Create: `a03-contract-audit/backend/tests/test_ingestion_reliability.py`
- Modify: `a03-contract-audit/scripts/quality_gate.py`
- Modify: `a03-contract-audit/scripts/quality_gate.ps1`
- Modify: `a03-contract-audit/backend/tests/test_quality_gate.py`
- Modify: `a03-contract-audit/README.md`

- [ ] **Step 1: 写验收汇总和门禁编排失败测试**

```python
def test_gate_rejects_technical_failures_false_ready_and_weak_elements():
    report = evaluate_ingestion(
        valid_results=[{"status": "failed", "error_code": "OCR_UNAVAILABLE"}],
        invalid_results=[{"status": "failed", "contract_id": None}],
        classification={"high_confidence_false_ready": 1},
        element_report={"overall": {"f1": 0.79}, "by_field": {"subject": {"f1": 0.0}}},
    )
    assert report.passed is False
    assert set(report.failures) == {
        "valid_contract_terminal_status",
        "ocr_unavailable",
        "classification_false_ready",
        "element_macro_f1",
        "element_zero_field",
    }


def test_quality_gate_adds_contract_set_step_only_when_explicit(tmp_path):
    config = make_config(tmp_path, contract_set_dir=tmp_path / "contracts")
    names = [step.name for step in quality_gate.default_steps(config)]
    assert names[0] == "contract-set"
```

- [ ] **Step 2: 运行评测和质量门禁测试并确认红灯**

Run: `Set-Location a03-contract-audit/backend; .\.venv\Scripts\python.exe -m pytest tests/test_ingestion_reliability.py tests/test_quality_gate.py -q`

Expected: FAIL，统一导入可靠性评测尚不存在。

- [ ] **Step 3: 实现结构化验收报告与显式路径参数**

`python -m evaluation.ingestion_reliability --dataset <目录> --output ../outputs/contract-set-gate/report.json` 必须：

1. 按清单区分 50 个有效输入和 2 个无效输入；补充损坏 PDF/DOCX 由评测器在内存中构造，不向合同目录写文件。
2. 对有效输入调用生产 `extract_document()`、分类器和证据化六要素抽取。
3. 对无效输入调用 `validate_upload()`，验证 `contract_id` 为空的规则层结果。
4. 调用现有 `evaluation.elements.evaluate_dataset()` 计算字段宏 F1。
5. 对照清单 `contract_type` 计算分类混淆矩阵、高置信度精确率和自动就绪错误数；开关关闭时自动就绪数必须为 0，未来开关开启时高置信度精确率必须达到 0.95。
6. 检查有效项全为 `parsed/review_required`、`OCR_UNAVAILABLE=0`、高置信错误自动放行数为 0、overall F1 不低于 0.80、各字段 F1 大于 0。
7. 报告只保存 case ID、状态、错误码、指标和证据位置，不保存合同正文。

`quality_gate.ps1` 增加 `param([switch]$IncludeE2E, [string]$ContractSetDir)`；`quality_gate.py` 增加 `--contract-set-dir`，只有显式传入时才运行真实合同集，避免在无合同原件的 CI/开发机伪造通过。

- [ ] **Step 4: 运行门禁编排测试**

Run: `Set-Location a03-contract-audit/backend; .\.venv\Scripts\python.exe -m pytest tests/test_ingestion_reliability.py tests/test_element_metrics.py tests/test_quality_gate.py -q`

Expected: PASS，缺失数据集不会被标成已验收，显式数据集失败时质量门禁非零退出。

- [ ] **Step 5: 提交本任务**

```powershell
git add a03-contract-audit/backend/evaluation/ingestion_reliability.py a03-contract-audit/backend/tests/test_ingestion_reliability.py a03-contract-audit/scripts/quality_gate.py a03-contract-audit/scripts/quality_gate.ps1 a03-contract-audit/backend/tests/test_quality_gate.py a03-contract-audit/README.md
git commit -m "test: gate contract ingestion reliability"
```

## Task 11: 端到端验收与完成门禁

**Files:**
- Modify only if observed behavior requires correction: files from Tasks 1-10
- Runtime-only: `a03-contract-audit/outputs/contract-set-gate/`
- Runtime-only: `a03-contract-audit/.quality-gate/`

- [ ] **Step 1: 运行冻结合同集门禁**

Run: `Set-Location a03-contract-audit; powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\quality_gate.ps1 -ContractSetDir 'C:\Users\chentao\Desktop\测试合同'`

Expected:

- 50 份有效合同全部为 `parsed` 或 `review_required`。
- 9 份纯扫描 PDF 中 `OCR_UNAVAILABLE=0`。
- 2 份无效输入和补充损坏样本全部同步拒绝且 `contract_id` 为空。
- 高置信度错误自动放行数为 0。
- 六要素 overall F1 不低于 0.80，各字段 F1 均大于 0。

- [ ] **Step 2: 运行完整非 E2E 质量门禁**

Run: `Set-Location a03-contract-audit; powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\quality_gate.ps1`

Expected: evaluation、backend、frontend、type-check、build 全部退出 0，`.quality-gate/summary.json` 状态为 `passed`。

- [ ] **Step 3: 启动服务并运行浏览器验收**

Run: `Set-Location a03-contract-audit; powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\quality_gate.ps1 -IncludeE2E`

Expected: 正常、空、OCR 不可用、损坏文件、待确认和移动端 390x844 状态通过；页面无横向溢出，控制台无新增错误。

- [ ] **Step 4: 检查敏感数据与提交边界**

Run: `Set-Location a03-contract-audit; git diff --check; git status --short`

Expected: 不出现 `.env`、合同原件、数据库、日志、模型缓存、wheelhouse、`.venv`、`.quality-gate` 或 `outputs/` 的待提交内容。用户原有未跟踪项保持不变。

- [ ] **Step 5: 记录真实结论，不扩大指标**

最终说明必须分别列出：通过的自动化测试数量、冻结集逐项结果、OCR 真实测试状态、浏览器视口和未实测边界。构造真值只称为工程基线；正式法律 F1、PostgreSQL、Redis/Celery 生产拓扑、GPU、能耗和容量仍标记为未验收。
