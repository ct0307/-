# OCR Quality And Timeout Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve OCR quality metadata through the complete audit workflow and enforce a real operating-system-level OCR timeout without storing plaintext temporary files.

**Architecture:** Add a structured `DocumentParseResult` while keeping `extract_text()` backward compatible. Persist quality on `Contract`, surface it through existing APIs and UI, and generate a red system risk when review is required. Run production RapidOCR in a child Python process whose stdin/stdout protocol is bounded and whose lifetime is controlled by the parent.

**Tech Stack:** Python 3.11+/FastAPI, SQLAlchemy 2, Alembic, Celery, RapidOCR/ONNX Runtime, Vue 3/Pinia/TypeScript, Element Plus, Playwright, pytest.

---

## File Map

| File | Responsibility |
|---|---|
| `backend/app/services/parser/extractor.py` | Produce structured document text and quality metadata; retain text-only compatibility API |
| `backend/app/services/parser/ocr.py` | Keep in-process OCR core and supervise the production OCR child process |
| `backend/app/services/parser/ocr_worker.py` | Read PDF bytes from stdin and emit one versioned JSON result line |
| `backend/app/models/models.py` | Persist contract parse source, confidence, review flag and reason |
| `backend/alembic/versions/20260726_02_add_ocr_quality.py` | Incrementally add and remove OCR quality columns |
| `backend/app/services/audit/runner.py` | Apply quality metadata and add an idempotent red system risk |
| `backend/app/schemas/contract.py` | Expose quality through parse/audit/contract responses |
| `backend/app/schemas/batch.py` | Expose contract quality on each completed batch item |
| `backend/app/api/v1/endpoints/contracts.py` | Use structured parsing in upload/parse/audit responses |
| `backend/app/api/v1/endpoints/batches.py` | Load the batch item contract relationship efficiently |
| `frontend/src/api/types.ts` | Mirror contract, parse and audit quality fields |
| `frontend/src/api/batches.ts` | Mirror batch item quality fields |
| `frontend/src/stores/audit-session.ts` | Retain current document quality across parse and audit |
| `frontend/src/views/AuditView.vue` | Display review warning, confidence and batch review marker |
| `backend/tests/test_parser_contracts.py` | Verify structured native/OCR/mixed parsing |
| `backend/tests/test_ocr_process.py` | Verify process protocol, timeout termination and error mapping |
| `backend/tests/test_audit_runner_quality.py` | Verify persistence, status and system-risk idempotency |
| `backend/tests/test_batch_api.py` | Verify batch response quality fields without status-machine changes |
| `backend/tests/test_hard_indicator_smoke.py` | Verify incremental Alembic upgrade and rollback |
| `frontend/tests/ocr-quality.spec.ts` | Verify session state and presentation labels |
| `frontend/tests/ocr-quality-e2e.spec.ts` | Verify the rendered review warning and mobile wrapping with mocked APIs |

## Task 1: Structured Document Parse Result

**Files:**
- Modify: `backend/app/services/parser/extractor.py`
- Modify: `backend/tests/test_parser_contracts.py`

- [ ] **Step 1: Add failing structured-result tests**

Add imports and tests that assert native and OCR metadata, while keeping the existing `extract_text()` contract:

```python
from app.services.parser.extractor import DocumentParseResult


def test_text_pdf_returns_native_parse_result(monkeypatch):
    class TextPage:
        def extract_text(self) -> str:
            return "甲方：测试公司\n乙方：交付公司\n" + "合同正文" * 60

    monkeypatch.setattr(
        pdfplumber,
        "open",
        lambda _: nullcontext(type("Pdf", (), {"pages": [TextPage()]})()),
    )

    result = extractor._extract_pdf_result(b"text-pdf")

    assert result.source == "native"
    assert result.ocr_confidence is None
    assert result.requires_review is False


def test_mixed_pdf_preserves_low_ocr_confidence(monkeypatch):
    class TextPage:
        def extract_text(self) -> str:
            return "正常文字页" * 60

    monkeypatch.setattr(
        pdfplumber,
        "open",
        lambda _: nullcontext(type("Pdf", (), {"pages": [TextPage(), _EmptyPage()]})()),
    )
    monkeypatch.setattr(
        extractor,
        "ocr_pdf_bytes",
        lambda *_args, **_kwargs: OCRResult(
            text="低置信度扫描页",
            page_count=1,
            mean_confidence=0.41,
            page_texts=("低置信度扫描页",),
            requires_review=True,
        ),
    )

    result = extractor._extract_pdf_result(b"mixed-pdf")

    assert result.source == "mixed"
    assert result.ocr_confidence == 0.41
    assert result.requires_review is True
    assert result.review_reason == "OCR 平均置信度低于 75%"
```

- [ ] **Step 2: Run the tests and verify RED**

Run from `backend`:

```powershell
$env:PYTHONPATH='C:/tmp/codex-test-deps/pytest-8.3.5-py313;C:/tmp/codex-ocr-deps-20260726'
$env:PYTHONUTF8='1'
& 'C:/Users/chentao/Desktop/浙江省外包赛/a03-contract-audit/backend/.venv/Scripts/python.exe' -m pytest tests/test_parser_contracts.py -q
```

Expected: FAIL because `DocumentParseResult` and `_extract_pdf_result` do not exist.

- [ ] **Step 3: Implement the structured result and compatibility wrapper**

Add the type and route file parsing through it:

```python
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class DocumentParseResult:
    text: str
    source: Literal["native", "ocr", "mixed"]
    ocr_confidence: float | None = None
    requires_review: bool = False
    review_reason: str | None = None


def extract_document(file_path: str) -> DocumentParseResult:
    data = _read_decrypted(file_path)
    lower = file_path.lower()
    if lower.endswith(".pdf"):
        return _extract_pdf_result(data)
    if lower.endswith(".docx"):
        return DocumentParseResult(_extract_docx_bytes(data), "native")
    if lower.endswith(".txt"):
        return DocumentParseResult(data.decode("utf-8", errors="ignore"), "native")
    raise ValueError(f"不支持的文件类型: {file_path}")


def extract_text(file_path: str) -> str:
    return extract_document(file_path).text
```

Rename the structured PDF implementation to `_extract_pdf_result()`. Convert each native early return to `DocumentParseResult(text, "native")`. Convert OCR output using:

```python
source = "mixed" if text or any(part.strip() for part in parts) else "ocr"
review_reason = None
if result.requires_review:
    threshold = int(settings.OCR_MIN_CONFIDENCE * 100)
    review_reason = f"OCR 平均置信度低于 {threshold}%" if result.text else "OCR 未识别出有效文本"
return DocumentParseResult(
    text=merged_text,
    source=source,
    ocr_confidence=result.mean_confidence,
    requires_review=result.requires_review,
    review_reason=review_reason,
)
```

Keep `_extract_pdf_bytes(data) -> str` as a compatibility wrapper around `_extract_pdf_result(data).text` so existing focused tests and internal callers continue to work.

- [ ] **Step 4: Run parser tests and verify GREEN**

Run the Step 2 command. Expected: all tests in `test_parser_contracts.py` pass.

- [ ] **Step 5: Commit Task 1**

```powershell
git add -- a03-contract-audit/backend/app/services/parser/extractor.py a03-contract-audit/backend/tests/test_parser_contracts.py
git commit -m "feat: preserve document parse quality"
```

## Task 2: Operating-System-Level OCR Timeout

**Files:**
- Create: `backend/app/services/parser/ocr_worker.py`
- Create: `backend/tests/test_ocr_process.py`
- Modify: `backend/app/services/parser/ocr.py`

- [ ] **Step 1: Add failing process-timeout and protocol tests**

Create `test_ocr_process.py`:

```python
import subprocess
import sys
import time

import pytest

from app.services.parser.ocr import OCRError, OCRTimeout, _communicate_with_timeout, _parse_worker_result


def test_child_process_is_terminated_at_timeout():
    process = subprocess.Popen(
        [sys.executable, "-c", "import sys,time; sys.stdin.buffer.read(); time.sleep(30)"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    started = time.monotonic()

    with pytest.raises(OCRTimeout):
        _communicate_with_timeout(process, b"pdf", timeout_seconds=0.05)

    assert time.monotonic() - started < 3
    assert process.poll() is not None


def test_worker_protocol_rejects_missing_result_marker():
    with pytest.raises(OCRError, match="响应协议无效"):
        _parse_worker_result(b"third-party log only\n")
```

- [ ] **Step 2: Run the new tests and verify RED**

```powershell
$env:PYTHONPATH='C:/tmp/codex-test-deps/pytest-8.3.5-py313;C:/tmp/codex-ocr-deps-20260726'
$env:PYTHONUTF8='1'
& 'C:/Users/chentao/Desktop/浙江省外包赛/a03-contract-audit/backend/.venv/Scripts/python.exe' -m pytest tests/test_ocr_process.py -q
```

Expected: collection FAIL because the process helpers do not exist.

- [ ] **Step 3: Split the in-process core from the production supervisor**

In `ocr.py`, rename the current body to `_ocr_pdf_bytes_in_process(...)`. Keep its existing resource checks and cooperative timing. Add a parent supervisor and stable protocol:

```python
import json
import subprocess
import sys

_WORKER_RESULT_PREFIX = b"A03_OCR_RESULT_V1="
_ERROR_TYPES = {
    "OCRError": OCRError,
    "OCRUnavailable": OCRUnavailable,
    "OCRLimitExceeded": OCRLimitExceeded,
    "OCRTimeout": OCRTimeout,
}


def _communicate_with_timeout(
    process: subprocess.Popen[bytes], data: bytes, *, timeout_seconds: float
) -> tuple[bytes, bytes]:
    try:
        return process.communicate(input=data, timeout=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        process.terminate()
        try:
            process.communicate(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
        raise OCRTimeout(f"OCR 处理超过 {timeout_seconds:g} 秒") from exc


def _parse_worker_result(stdout: bytes) -> OCRResult:
    line = next((line for line in reversed(stdout.splitlines()) if line.startswith(_WORKER_RESULT_PREFIX)), None)
    if line is None:
        raise OCRError("OCR 子进程响应协议无效")
    payload = json.loads(line[len(_WORKER_RESULT_PREFIX):].decode("utf-8"))
    if not payload.get("ok"):
        error_type = _ERROR_TYPES.get(payload.get("error_type"), OCRError)
        raise error_type(str(payload.get("message") or "OCR 子进程失败"))
    return OCRResult(
        text=payload["result"]["text"],
        page_count=int(payload["result"]["page_count"]),
        mean_confidence=float(payload["result"]["mean_confidence"]),
        page_texts=tuple(payload["result"].get("page_texts", [])),
        requires_review=bool(payload["result"]["requires_review"]),
    )
```

The public `ocr_pdf_bytes()` validates parameters, uses `_ocr_pdf_bytes_in_process()` when `engine` is explicitly supplied, and otherwise starts:

```python
command = [
    sys.executable,
    "-m",
    "app.services.parser.ocr_worker",
    "--max-pages", str(max_pages),
    "--max-page-pixels", str(max_page_pixels),
    "--dpi", str(dpi),
    "--timeout-seconds", str(timeout_seconds),
    "--min-confidence", str(min_confidence),
]
process = subprocess.Popen(
    command,
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
)
stdout, stderr = _communicate_with_timeout(process, data, timeout_seconds=timeout_seconds)
if process.returncode not in (0, None) and _WORKER_RESULT_PREFIX not in stdout:
    detail = stderr.decode("utf-8", errors="replace")[-1000:]
    raise OCRUnavailable(f"OCR 子进程启动或执行失败: {detail or process.returncode}")
return _parse_worker_result(stdout)
```

- [ ] **Step 4: Add the child worker entry point**

Create `ocr_worker.py` with argparse for the five numeric resource options. Read PDF bytes from `sys.stdin.buffer`, call `_ocr_pdf_bytes_in_process(data, engine=RapidOCREngine(), ...)`, and always emit one final protocol line:

```python
payload = {"ok": True, "result": asdict(result)}
sys.stdout.buffer.write(_WORKER_RESULT_PREFIX + json.dumps(payload, ensure_ascii=False).encode("utf-8") + b"\n")
```

For `OCRError`, emit `{"ok": false, "error_type": type(exc).__name__, "message": str(exc)}`. For an unexpected exception, use `error_type="OCRError"` and a generic message without PDF text. Return exit code 0 only for a valid result and 2 for structured failures.

- [ ] **Step 5: Verify timeout, injected-engine and real-engine paths**

```powershell
$env:PYTHONPATH='C:/tmp/codex-test-deps/pytest-8.3.5-py313;C:/tmp/codex-ocr-deps-20260726'
$env:PYTHONUTF8='1'
& 'C:/Users/chentao/Desktop/浙江省外包赛/a03-contract-audit/backend/.venv/Scripts/python.exe' -m pytest tests/test_ocr_process.py tests/test_parser_contracts.py tests/test_ocr_real_integration.py -q
```

Expected: all selected tests pass; the real integration test invokes the production child-process path for the scanned PDF.

- [ ] **Step 6: Commit Task 2**

```powershell
git add -- a03-contract-audit/backend/app/services/parser/ocr.py a03-contract-audit/backend/app/services/parser/ocr_worker.py a03-contract-audit/backend/tests/test_ocr_process.py
git commit -m "feat: enforce OCR process timeout"
```

## Task 3: Persist OCR Quality With Incremental Migration

**Files:**
- Modify: `backend/app/models/models.py`
- Create: `backend/alembic/versions/20260726_02_add_ocr_quality.py`
- Modify: `backend/tests/test_hard_indicator_smoke.py`

- [ ] **Step 1: Add a failing incremental migration test**

Generalize the helper and update existing callers to pass `"head"` or `"base"` explicitly:

```python
def _run_alembic(
    backend_dir: Path,
    database: Path,
    command: str,
    target: str,
) -> None:
    env = os.environ.copy()
    env.update({"DB_BACKEND": "sqlite", "SQLITE_PATH": database.as_posix()})
    completed = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", command, target],
        cwd=backend_dir,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
```

Then add:

```python
def test_ocr_quality_migration_preserves_existing_contract(tmp_path: Path):
    backend_dir = Path(__file__).resolve().parents[1]
    database = tmp_path / "incremental.db"
    _run_alembic(backend_dir, database, "upgrade", "20260726_01")
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "INSERT INTO users (id, username, password_hash, role, department) "
            "VALUES (1, 'legacy', 'hash', 'legal', '法务部')"
        )
        connection.exec_driver_sql(
            "INSERT INTO contracts "
            "(id, filename, storage_path, contract_type, department, status, uploaded_by, elements_json) "
            "VALUES (1, 'legacy.pdf', '/legacy.pdf', '', '法务部', 'done', 1, '{}')"
        )

    _run_alembic(backend_dir, database, "upgrade", "head")

    with engine.connect() as connection:
        row = connection.exec_driver_sql(
            "SELECT parse_source, ocr_confidence, requires_review, review_reason FROM contracts WHERE id=1"
        ).mappings().one()
    assert row == {
        "parse_source": "native",
        "ocr_confidence": None,
        "requires_review": 0,
        "review_reason": None,
    }
```

- [ ] **Step 2: Run the migration test and verify RED**

```powershell
$env:PYTHONPATH='C:/tmp/codex-test-deps/pytest-8.3.5-py313;C:/tmp/codex-ocr-deps-20260726'
$env:PYTHONUTF8='1'
& 'C:/Users/chentao/Desktop/浙江省外包赛/a03-contract-audit/backend/.venv/Scripts/python.exe' -m pytest tests/test_hard_indicator_smoke.py::test_ocr_quality_migration_preserves_existing_contract -q
```

Expected: FAIL because revision `20260726_02` and the quality columns do not exist.

- [ ] **Step 3: Add ORM fields and the second Alembic revision**

Add to `Contract`:

```python
parse_source: Mapped[str] = mapped_column(String(16), default="native", server_default="native")
ocr_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
requires_review: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
review_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
```

Import `Boolean`, `Float`, and `false` from SQLAlchemy. In migration `20260726_02_add_ocr_quality.py`, set `down_revision = "20260726_01"`, add the four columns in `upgrade()`, and drop them in reverse order in `downgrade()`.

- [ ] **Step 4: Run migration and metadata parity tests**

```powershell
$env:PYTHONPATH='C:/tmp/codex-test-deps/pytest-8.3.5-py313;C:/tmp/codex-ocr-deps-20260726'
$env:PYTHONUTF8='1'
& 'C:/Users/chentao/Desktop/浙江省外包赛/a03-contract-audit/backend/.venv/Scripts/python.exe' -m pytest tests/test_hard_indicator_smoke.py -q
```

Expected: all hard-indicator smoke tests pass, including head-to-base rollback.

- [ ] **Step 5: Commit Task 3**

```powershell
git add -- a03-contract-audit/backend/app/models/models.py a03-contract-audit/backend/alembic/versions/20260726_02_add_ocr_quality.py a03-contract-audit/backend/tests/test_hard_indicator_smoke.py
git commit -m "feat: persist OCR review quality"
```

## Task 4: Enforce The Audit Quality Gate

**Files:**
- Modify: `backend/app/services/audit/runner.py`
- Create: `backend/tests/test_audit_runner_quality.py`

- [ ] **Step 1: Add failing audit quality tests**

Create a SQLite session fixture and two contracts, then monkeypatch `runner.extract_document` and `runner.audit_contract`. The low-confidence test must assert:

```python
result = run_audit(db, contract)
db.refresh(contract)
risks = db.query(Risk).filter(Risk.contract_id == contract.id).all()

assert contract.status == "review_required"
assert contract.parse_source == "ocr"
assert contract.ocr_confidence == 0.42
assert contract.requires_review is True
assert result["requires_review"] is True
assert [risk.category for risk in risks].count("扫描件识别质量不足") == 1
assert next(risk for risk in risks if risk.category == "扫描件识别质量不足").tier == "red"
```

Call `run_audit()` a second time and assert the quality risk count remains one. Add a high-confidence/native test asserting `status == "done"` and no quality risk.

Add a short native-text test asserting `contract.requires_review is True`, `contract.review_reason == "合同文本长度不足 200 字"`, final status `review_required`, and exactly one “文本解析失败” risk after repeated execution.

- [ ] **Step 2: Run the new tests and verify RED**

```powershell
$env:PYTHONPATH='C:/tmp/codex-test-deps/pytest-8.3.5-py313;C:/tmp/codex-ocr-deps-20260726'
$env:PYTHONUTF8='1'
& 'C:/Users/chentao/Desktop/浙江省外包赛/a03-contract-audit/backend/.venv/Scripts/python.exe' -m pytest tests/test_audit_runner_quality.py -q
```

Expected: FAIL because `run_audit()` still calls `extract_text()` and returns no quality fields.

- [ ] **Step 3: Apply parse quality and generate the system risk**

In `runner.py`, replace `extract_text()` with `extract_document()`. Add:

```python
def apply_parse_quality(contract: Contract, parsed: DocumentParseResult) -> None:
    contract.parse_source = parsed.source
    contract.ocr_confidence = parsed.ocr_confidence
    contract.requires_review = parsed.requires_review
    contract.review_reason = parsed.review_reason
```

Before branching, if the extracted text is shorter than 200 characters, set `contract.requires_review = True` and preserve an existing OCR reason or assign `contract.review_reason = "合同文本长度不足 200 字"`. Delete existing contract risks before either the short-text or normal-risk branch so repeated execution is idempotent.

For short text, write the existing “文本解析失败” risk and skip `audit_contract()` without returning early. For normal text, write the automatic risks. After either branch, add one OCR-specific system risk only when `parsed.requires_review` and `parsed.source in {"ocr", "mixed"}`:

```python
db.add(Risk(
    contract_id=contract.id,
    agent="system",
    level="high",
    category="扫描件识别质量不足",
    original_text=f"OCR 平均置信度：{(parsed.ocr_confidence or 0) * 100:.1f}%",
    basis=parsed.review_reason or "OCR 结果未达到自动采信门槛。",
    suggestion="请对照合同原件完成人工复核后再采信自动审查结论。",
    confidence=int(round((parsed.ocr_confidence or 0) * 100)),
    tier="red",
    review_status="pending",
    rag_sources="[]",
))
```

Set final contract status from the persisted `contract.requires_review`: `review_required` when true, otherwise `done`. Return the final persisted `requires_review`, `ocr_confidence`, and `review_reason` from `run_audit()` so the short-text and OCR paths use the same response contract.

- [ ] **Step 4: Run quality and existing evidence tests**

```powershell
$env:PYTHONPATH='C:/tmp/codex-test-deps/pytest-8.3.5-py313;C:/tmp/codex-ocr-deps-20260726'
$env:PYTHONUTF8='1'
& 'C:/Users/chentao/Desktop/浙江省外包赛/a03-contract-audit/backend/.venv/Scripts/python.exe' -m pytest tests/test_audit_runner_quality.py tests/test_audit_evidence.py tests/test_batch_api.py -q
```

Expected: all selected tests pass and batch task status remains terminal `done` even when the contract needs review.

- [ ] **Step 5: Commit Task 4**

```powershell
git add -- a03-contract-audit/backend/app/services/audit/runner.py a03-contract-audit/backend/tests/test_audit_runner_quality.py
git commit -m "feat: require review for low-quality OCR"
```

## Task 5: Expose Quality Through Contract And Batch APIs

**Files:**
- Modify: `backend/app/models/models.py`
- Modify: `backend/app/schemas/contract.py`
- Modify: `backend/app/schemas/batch.py`
- Modify: `backend/app/api/v1/endpoints/contracts.py`
- Modify: `backend/app/api/v1/endpoints/batches.py`
- Modify: `backend/app/tasks/audit_tasks.py`
- Modify: `backend/tests/test_batch_api.py`
- Create: `backend/tests/test_contract_quality_api.py`

- [ ] **Step 1: Add failing API contract tests**

Create `test_contract_quality_api.py` with a local in-memory database and invoke the endpoint function directly:

```python
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.v1.endpoints import contracts
from app.db.session import Base
from app.models.models import Contract, User
from app.services.parser.extractor import DocumentParseResult


def test_parse_response_persists_ocr_quality(monkeypatch, tmp_path):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = User(username="legal", password_hash="hash", role="legal", department="法务部")
        db.add(user)
        db.flush()
        contract = Contract(
            filename="scan.pdf",
            storage_path=str(tmp_path / "scan.pdf"),
            department=user.department,
            uploaded_by=user.id,
        )
        db.add(contract)
        db.commit()
        monkeypatch.setattr(
            contracts,
            "extract_document",
            lambda _path: DocumentParseResult(
                "有效文本" * 60,
                "ocr",
                0.42,
                True,
                "OCR 平均置信度低于 75%",
            ),
        )
        monkeypatch.setattr(contracts, "extract_elements_with_llm", lambda _text: {})

        response = contracts.parse_contract(contract.id, db=db, user=user)

        db.refresh(contract)
        assert response.requires_review is True
        assert response.ocr_confidence == 0.42
        assert contract.requires_review is True
        assert contract.review_reason == "OCR 平均置信度低于 75%"
```

Extend a completed batch-item fixture by setting the related contract quality fields, then assert:

```python
payload = BatchOut.model_validate(batch).model_dump()
item = payload["items"][0]
assert item["status"] == "done"
assert item["requires_review"] is True
assert item["ocr_confidence"] == 0.42
assert item["review_reason"] == "OCR 平均置信度低于 75%"
```

- [ ] **Step 2: Run API tests and verify RED**

```powershell
$env:PYTHONPATH='C:/tmp/codex-test-deps/pytest-8.3.5-py313;C:/tmp/codex-ocr-deps-20260726'
$env:PYTHONUTF8='1'
& 'C:/Users/chentao/Desktop/浙江省外包赛/a03-contract-audit/backend/.venv/Scripts/python.exe' -m pytest tests/test_contract_quality_api.py tests/test_batch_api.py -q
```

Expected: FAIL because the response schemas have no quality fields.

- [ ] **Step 3: Add schema fields and batch relationship properties**

Add the quality fields with safe defaults to `ContractOut`, a new `ParseResponse`, `AuditResponse`, and `BatchItemOut`:

```python
requires_review: bool = False
ocr_confidence: float | None = None
review_reason: str | None = None
```

Add `contract: Mapped["Contract"] = relationship(lazy="joined")` to `AuditBatchItem` and read-only properties with the same three names that delegate to `self.contract`. This avoids duplicated persisted quality while preventing a 200-item N+1 query.

- [ ] **Step 4: Migrate contract endpoints and async return values**

In `contracts.py`, use `extract_document()` for batch-upload parsing and the explicit parse endpoint, call `apply_parse_quality()`, and return `ParseResponse`. Populate synchronous `AuditResponse` from the `run_audit()` result.

In `audit_tasks.py`, include the three quality fields in the serializable task result. Do not add `review_required` to `BatchItemStatus`; machine completion remains `done`.

- [ ] **Step 5: Run API and task tests**

Run the Step 2 command. Expected: all contract-quality and batch tests pass.

- [ ] **Step 6: Commit Task 5**

```powershell
git add -- a03-contract-audit/backend/app/models/models.py a03-contract-audit/backend/app/schemas/contract.py a03-contract-audit/backend/app/schemas/batch.py a03-contract-audit/backend/app/api/v1/endpoints/contracts.py a03-contract-audit/backend/app/api/v1/endpoints/batches.py a03-contract-audit/backend/app/tasks/audit_tasks.py a03-contract-audit/backend/tests/test_batch_api.py a03-contract-audit/backend/tests/test_contract_quality_api.py
git commit -m "feat: expose OCR review state"
```

## Task 6: Display Review State In Single And Batch Workflows

**Files:**
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/api/batches.ts`
- Modify: `frontend/src/stores/audit-session.ts`
- Modify: `frontend/src/views/AuditView.vue`
- Create: `frontend/src/utils/ocr-quality.ts`
- Create: `frontend/tests/ocr-quality.spec.ts`
- Create: `frontend/tests/ocr-quality-e2e.spec.ts`

- [ ] **Step 1: Add failing quality-format tests**

Create `ocr-quality.ts` test imports before implementation:

```typescript
import { expect, test } from '@playwright/test'
import { formatOcrConfidence, reviewStatusLabel } from '../src/utils/ocr-quality'

test('formats bounded OCR confidence for review display', () => {
  expect(formatOcrConfidence(0.423)).toBe('42.3%')
  expect(formatOcrConfidence(null)).toBe('未提供')
})

test('keeps machine completion distinct from business review', () => {
  expect(reviewStatusLabel({ status: 'done', requires_review: true })).toBe('需人工复核')
  expect(reviewStatusLabel({ status: 'done', requires_review: false })).toBe('已完成')
})
```

- [ ] **Step 2: Run the frontend test and verify RED**

```powershell
npm.cmd run test -- tests/ocr-quality.spec.ts
```

Expected: FAIL because `src/utils/ocr-quality.ts` does not exist.

- [ ] **Step 3: Add frontend types, state and formatter**

Add the three quality fields to `ContractOut`, `ParseResult`, `AuditResult`, and `AuditBatchItem`. Expand `RiskOut.agent` to include `system`.

In the audit-session store add:

```typescript
const requiresReview = ref(false)
const ocrConfidence = ref<number | null>(null)
const reviewReason = ref('')

function applyQuality(source: ParseResult | AuditResult) {
  requiresReview.value = source.requires_review ?? false
  ocrConfidence.value = source.ocr_confidence ?? null
  reviewReason.value = source.review_reason ?? ''
}
```

Call `applyQuality(parsed)` after parse and `applyQuality(res)` after audit; clear all three fields in `reset()` and return them from the store.

Implement `formatOcrConfidence()` by clamping to `[0, 1]` and formatting one decimal percentage. Implement `reviewStatusLabel()` so `requires_review` takes precedence over machine status.

- [ ] **Step 4: Add accessible single and batch review indicators**

In `AuditView.vue`, render an unframed warning band above result KPIs:

```vue
<div v-if="session.requiresReview" class="ocr-review-alert" role="alert">
  <el-icon><WarningFilled /></el-icon>
  <div>
    <strong>扫描件需人工复核</strong>
    <p>{{ session.reviewReason }} · OCR 置信度 {{ formatOcrConfidence(session.ocrConfidence) }}</p>
  </div>
</div>
```

Change the result status from hard-coded “已完成” to `session.requiresReview ? '待人工复核' : '已完成'`. In batch rows, check `item.requires_review` before ordinary `done` and display a warning tag labeled “需人工复核”. Add responsive CSS so the warning content wraps below 640px and never overlaps actions.

- [ ] **Step 5: Add a rendered low-confidence workflow test**

Create `ocr-quality-e2e.spec.ts`. Reuse `E2E_BASE_URL`, skip only when it is absent, and mock all API calls needed by the workflow. The test must route login, runtime, lookups, upload, parse, audit, and risks. The core response fixtures are:

```typescript
const parseResult = {
  contract_id: 1,
  elements: {},
  text_length: 480,
  requires_review: true,
  ocr_confidence: 0.423,
  review_reason: 'OCR 平均置信度低于 75%',
}
const auditResult = {
  contract_id: 1,
  status: 'review_required',
  risk_count: 1,
  cross_checks: [],
  ...parseResult,
}
const risks = [{
  id: 1,
  agent: 'system',
  level: 'high',
  category: '扫描件识别质量不足',
  original_text: 'OCR 平均置信度：42.3%',
  basis: parseResult.review_reason,
  suggestion: '请人工复核',
  confidence: 42,
  tier: 'red',
  review_status: 'pending',
  rag_sources: [],
}]
```

After mocked login, navigate to `/audit`, upload an in-memory `scan.pdf` through the first file input, and click “启动合规审查”. Assert:

```typescript
await expect(page.getByRole('alert')).toContainText('扫描件需人工复核')
await expect(page.getByRole('alert')).toContainText('42.3%')
await expect(page.getByText('待人工复核', { exact: true })).toBeVisible()
await expect(page.getByText('扫描件识别质量不足')).toBeVisible()
```

Set the viewport to `390x844`, assert `document.documentElement.scrollWidth - window.innerWidth <= 0`, and capture a Playwright screenshot for visual inspection.

- [ ] **Step 6: Run focused tests, rendered E2E, type-check and production build**

```powershell
npm.cmd run test -- tests/ocr-quality.spec.ts tests/batch-store.spec.ts
npm.cmd run type-check
npm.cmd run build
```

In a second terminal start the already-installed frontend runtime, then execute the rendered test:

```powershell
npm.cmd run dev -- --host 127.0.0.1
$env:E2E_BASE_URL='http://127.0.0.1:5173'
npm.cmd run test -- tests/ocr-quality-e2e.spec.ts
```

Expected: focused tests and the rendered E2E pass, type-check exits 0, Vite reports a successful production build, and the desktop/mobile screenshots show no overlap.

- [ ] **Step 7: Commit Task 6**

```powershell
git add -- a03-contract-audit/frontend/src/api/types.ts a03-contract-audit/frontend/src/api/batches.ts a03-contract-audit/frontend/src/stores/audit-session.ts a03-contract-audit/frontend/src/views/AuditView.vue a03-contract-audit/frontend/src/utils/ocr-quality.ts a03-contract-audit/frontend/tests/ocr-quality.spec.ts a03-contract-audit/frontend/tests/ocr-quality-e2e.spec.ts
git commit -m "feat: show OCR review requirements"
```

## Task 7: Update Evidence And Run Full Acceptance

**Files:**
- Modify: `docs/evaluation/hard-indicator-matrix.md`
- Modify: `PROGRESS.md`

- [ ] **Step 1: Update evidence without overstating accuracy**

Change the OCR matrix row to state that quality metadata, forced process timeout and manual-review presentation are code-verified. Keep frozen-scan accuracy explicitly “待实测”. Add the new focused commands and migration evidence to `PROGRESS.md`; update pass counts only from fresh output.

- [ ] **Step 2: Run the complete backend suite**

```powershell
$env:PYTHONPATH='C:/tmp/codex-test-deps/pytest-8.3.5-py313;C:/tmp/codex-ocr-deps-20260726'
$env:PYTHONUTF8='1'
& 'C:/Users/chentao/Desktop/浙江省外包赛/a03-contract-audit/backend/.venv/Scripts/python.exe' -m pytest tests -q
```

Expected: zero failures. Record the exact pass and warning counts.

- [ ] **Step 3: Run the complete frontend suite and build gates**

```powershell
npm.cmd run test
npm.cmd run type-check
npm.cmd run build
```

Expected: zero test failures, type-check exit 0, and successful production build. Preserve any intentional Playwright skip in the reported count.

- [ ] **Step 4: Verify repository and Compose structure**

```powershell
git diff --check
& 'C:/Users/chentao/Desktop/浙江省外包赛/a03-contract-audit/backend/.venv/Scripts/python.exe' -c "import pathlib,yaml; data=yaml.safe_load(pathlib.Path('docker-compose.yml').read_text(encoding='utf-8')); assert sorted(data['services']) == sorted(['backend','frontend','postgres','redis','scheduler','worker']); print(','.join(sorted(data['services'])))"
```

Expected: no Git whitespace errors and exactly the existing six Compose services. Do not claim container startup because Docker is unavailable on this machine.

- [ ] **Step 5: Commit evidence updates**

```powershell
git add -- a03-contract-audit/docs/evaluation/hard-indicator-matrix.md a03-contract-audit/PROGRESS.md
git commit -m "docs: record OCR quality hardening evidence"
```

- [ ] **Step 6: Perform final review before push**

Run `git status --short --branch`, `git log --oneline origin/codex/enterprise-hard-indicators..HEAD`, and inspect the complete diff from the remote branch. Confirm:

- no plaintext contract fixtures or generated OCR output are tracked;
- no external dependency or Compose service was added;
- batch task terminal semantics remain unchanged;
- accuracy, 50+2 throughput and Docker runtime remain labeled as external acceptance items.

- [ ] **Step 7: Push the feature branch, but do not merge**

First use the configured origin. If the known inactive HTTPS proxy fails and existing SSH authentication still validates, use the already established one-command SSH push override without changing repository config:

```powershell
git -c remote.origin.pushurl=ssh://git@ssh.github.com:443/ct0307/-.git push origin codex/enterprise-hard-indicators
```

Expected: remote branch advances to the local HEAD. Verify with `git ls-remote` over SSH. Create a PR for `codex/enterprise-hard-indicators -> master`; do not merge until review is clean.
