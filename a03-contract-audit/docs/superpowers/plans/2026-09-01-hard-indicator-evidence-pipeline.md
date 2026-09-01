# 硬指标证据流水线实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. 本项目明确禁止使用子代理，全部任务由当前主代理顺序执行并在每次提交前自行审查。

**Goal:** 建立能强制校验输入、执行 50+2 批量验收和 OpenClaw/GPU 3+5 基准，并生成可审计证据的模块化命令行流水线。

**Architecture:** 保留现有业务 API 和纯统计函数，在 `backend/evaluation` 内增加证据核心、批测执行器、基准执行器和报告器。各模块通过版本化 manifest 与追加式 JSONL 通信；CLI 统一参数、退出状态和脱敏规则，真实数据或设备缺失时只能输出 `blocked`。

**Tech Stack:** Python 3.11、argparse、dataclasses、Pydantic 2、httpx、pytest、JSON Schema Draft 2020-12；拟新增 `jsonschema==4.25.1`，必须先完成来源/许可证/漏洞审计并取得用户明确安装授权。

---

## 文件结构

| 路径 | 操作 | 单一职责 |
|---|---|---|
| `backend/requirements.txt` | 修改 | 固定 JSON Schema 执行库版本 |
| `backend/evaluation/__init__.py` | 创建 | 声明稳定评测包 |
| `backend/evaluation/schema.json` | 修改 | 冻结金标准 Draft 2020-12 契约 |
| `backend/evaluation/elements.py` | 修改 | Schema 校验、预测对齐与要素指标 |
| `backend/evaluation/evidence.py` | 创建 | manifest、哈希、脱敏和追加式事件 |
| `backend/evaluation/batch.py` | 创建 | 50+2 清单校验、API 调用、轮询与失败隔离 |
| `backend/evaluation/benchmark.py` | 修改 | 保留并收紧纯统计与可比性检查 |
| `backend/evaluation/benchmark_runner.py` | 创建 | 目标调用、3+5 完整轮次与原始测量 |
| `backend/evaluation/report.py` | 创建 | 校验证据完整性并生成 Markdown 报告 |
| `backend/evaluation/cli.py` | 修改 | 子命令、参数解析、模块分派与退出状态 |
| `backend/tests/test_element_metrics.py` | 修改 | 金标准与预测边界回归 |
| `backend/tests/test_evaluation_evidence.py` | 创建 | 证据不可覆盖、脱敏和状态测试 |
| `backend/tests/test_evaluation_batch.py` | 创建 | 50+2、轮询、超时、隔离与内存策略测试 |
| `backend/tests/test_benchmark_stats.py` | 修改 | 统计口径与轮次不足回归 |
| `backend/tests/test_benchmark_runner.py` | 创建 | 3+5 调用、目标可比性和响应脱敏测试 |
| `backend/tests/test_evaluation_report.py` | 创建 | 缺失证据、哈希冲突和状态聚合测试 |
| `backend/tests/test_evaluation_cli.py` | 创建 | 子命令和退出状态测试 |
| `.gitignore` | 修改 | 排除本地原始运行目录 |
| `docs/evaluation/element-accuracy-protocol.md` | 修改 | 更新双人复核和新 CLI 命令 |
| `docs/evaluation/hard-indicator-matrix.md` | 修改 | PostgreSQL 降级为代码就绪待实测 |
| `PROGRESS.md` | 修改 | 完整功能闭环后记录验证证据 |

## 统一约定

```python
EXIT_OK = 0
EXIT_INVALID = 2
EXIT_ERROR = 3
EXIT_FAILED = 4
EXIT_BLOCKED = 5

RUN_STATUSES = frozenset({"passed", "failed", "blocked", "error"})
SCHEMA_VERSION = "1.0"
```

所有测试命令均从 `a03-contract-audit/backend` 执行；Git 命令从外层仓库根目录 `浙江省外包赛` 执行。每次提交只暂存任务列出的文件，不暂存现有 `a03-contract-audit/outputs/`。

### Task 1：依赖门禁与冻结金标准强校验

**Files:**
- Modify: `backend/requirements.txt`
- Create: `backend/evaluation/__init__.py`
- Modify: `backend/evaluation/schema.json`
- Modify: `backend/evaluation/elements.py`
- Modify: `backend/tests/test_element_metrics.py`

- [ ] **Step 1：先写非法 Schema 和双人复核失败测试**

在 `backend/tests/test_element_metrics.py` 增加以下用例，并把现有合法夹具中的 `reviewer` 改为 `reviewers` 与 `review_status`：

```python
def _valid_gold_record() -> dict:
    return {
        "case_id": "case-1",
        "file": "case-1.pdf",
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
            "payment_terms": ["首付款", "验收款"],
        },
    }


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda row: row.update(document_kind="jpg"), "document_kind"),
        (lambda row: row.update(reviewers=["reviewer-a"]), "reviewers"),
        (lambda row: row["gold"].update(payment_terms="首付款"), "payment_terms"),
    ],
)
def test_gold_record_enforces_json_schema(mutate, message):
    row = _valid_gold_record()
    mutate(row)
    with pytest.raises(ValueError, match=message):
        validate_gold_record(row)


def test_adjudicated_record_requires_adjudicator():
    row = _valid_gold_record()
    row["review_status"] = "adjudicated"
    with pytest.raises(ValueError, match="adjudicator"):
        validate_gold_record(row)
```

- [ ] **Step 2：运行测试并确认旧实现会接受非法数据**

Run: `pytest tests/test_element_metrics.py -q`

Expected: FAIL；至少包含旧实现不识别 `reviewers` 或没有拒绝非法 `document_kind/payment_terms` 的失败。

- [ ] **Step 3：执行依赖安全门禁并等待用户明确授权**

向用户说明：`jsonschema` 来源为 PyPI 官方项目，目的为执行仓库现有 Draft 2020-12 Schema；计划固定 `4.25.1`。只读检查以下信息，不安装：

```powershell
python -m pip index versions jsonschema
python -m pip download --no-deps --dest $env:TEMP jsonschema==4.25.1
python -m pip hash "$env:TEMP\jsonschema-4.25.1-py3-none-any.whl"
```

核对 PyPI 元数据、许可证、维护状态、wheel 哈希与公开漏洞记录。未获得用户明确同意时停止 Task 1，不修改 `requirements.txt`，不执行安装。

- [ ] **Step 4：获批后固定并安装依赖**

在 `backend/requirements.txt` 的“数据校验/配置”段加入：

```text
jsonschema==4.25.1
```

Run: `python -m pip install -r requirements.txt`

Expected: 安装退出码 0；现有固定依赖不被降级。

- [ ] **Step 5：升级 Schema 并接入 Draft 2020-12 验证器**

把 `schema.json` 的 `reviewer` 替换为以下字段和条件：

```json
{
  "reviewers": {
    "type": "array",
    "minItems": 2,
    "maxItems": 2,
    "uniqueItems": true,
    "items": {"type": "string", "minLength": 1}
  },
  "review_status": {"enum": ["agreed", "adjudicated"]},
  "adjudicator": {"type": "string", "minLength": 1}
}
```

根对象 `required` 必须包含 `reviewers` 和 `review_status`；使用 `if/then` 要求 `review_status=adjudicated` 时必须出现 `adjudicator`。在 `elements.py` 中加载同目录 Schema：

```python
from pathlib import Path

from jsonschema import Draft202012Validator

_SCHEMA_PATH = Path(__file__).with_name("schema.json")
_GOLD_SCHEMA = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
_GOLD_VALIDATOR = Draft202012Validator(_GOLD_SCHEMA)


def validate_gold_record(record: Mapping[str, Any]) -> None:
    errors = sorted(_GOLD_VALIDATOR.iter_errors(record), key=lambda item: list(item.path))
    if not errors:
        return
    first = errors[0]
    location = ".".join(str(part) for part in first.absolute_path) or "$"
    raise ValueError(f"金标准不符合 schema.json: {location}: {first.message}")
```

- [ ] **Step 6：补齐预测集对齐规则并运行测试**

在 `evaluate_dataset` 入口拒绝未知预测 ID；缺失预测继续按六字段漏报计零分：

```python
gold_ids = {str(record["case_id"]) for record in gold_records}
unknown_ids = sorted(set(predictions) - gold_ids)
if unknown_ids:
    raise ValueError(f"预测集包含未知 case_id: {', '.join(unknown_ids)}")
```

Run: `pytest tests/test_element_metrics.py -q`

Expected: PASS，非法 `document_kind`、单审核人、字符串付款节点和缺少裁决人均被拒绝。

- [ ] **Step 7：提交金标准契约**

```powershell
git add -- a03-contract-audit/backend/requirements.txt a03-contract-audit/backend/evaluation/__init__.py a03-contract-audit/backend/evaluation/schema.json a03-contract-audit/backend/evaluation/elements.py a03-contract-audit/backend/tests/test_element_metrics.py
git commit -m "feat: enforce frozen evaluation schema"
```

### Task 2：建立版本化证据核心

**Files:**
- Create: `backend/evaluation/evidence.py`
- Create: `backend/tests/test_evaluation_evidence.py`
- Modify: `.gitignore`

- [ ] **Step 1：写不可覆盖、脱敏和哈希测试**

```python
def test_evidence_writer_appends_events_without_overwriting(tmp_path):
    writer = EvidenceWriter.create(tmp_path, run_id="run-1", command="elements")
    writer.append("elements", {"case_id": "case-1"})
    writer.append("elements", {"case_id": "case-2"})
    rows = [json.loads(line) for line in (tmp_path / "run-1" / "elements.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [row["payload"]["case_id"] for row in rows] == ["case-1", "case-2"]


def test_redact_removes_secrets_and_contract_text():
    payload = redact({"Authorization": "Bearer secret", "contract_text": "合同正文", "status": "done"})
    assert payload == {"Authorization": "[REDACTED]", "contract_text": "[REDACTED]", "status": "done"}


def test_sha256_file_binds_exact_bytes(tmp_path):
    path = tmp_path / "input.jsonl"
    path.write_bytes(b"one\n")
    assert sha256_file(path) == hashlib.sha256(b"one\n").hexdigest()
```

- [ ] **Step 2：运行测试确认模块缺失**

Run: `pytest tests/test_evaluation_evidence.py -q`

Expected: FAIL，提示 `evaluation.evidence` 不存在。

- [ ] **Step 3：实现 manifest、脱敏和追加写入**

`evidence.py` 定义 `RunManifest`、`EvidenceWriter`、`sha256_file` 和 `redact`。关键接口固定为：

```python
@dataclass(frozen=True)
class RunManifest:
    schema_version: str
    run_id: str
    command: str
    status: str
    created_at: str
    git_commit: str
    git_dirty: bool
    inputs: dict[str, str]
    environment: dict[str, str]
    modules: dict[str, str]


class EvidenceWriter:
    def __init__(self, run_dir: Path, *, run_id: str, command: str) -> None:
        self.run_dir = run_dir
        self.run_id = run_id
        self.command = command

    @classmethod
    def create(cls, root: Path, *, run_id: str, command: str) -> "EvidenceWriter":
        run_dir = root / run_id
        run_dir.mkdir(parents=True, exist_ok=False)
        writer = cls(run_dir, run_id=run_id, command=command)
        writer.write_manifest(status="error", modules={})
        return writer

    def append(self, stream: str, payload: Mapping[str, Any]) -> None:
        event = {
            "schema_version": SCHEMA_VERSION,
            "run_id": self.run_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": redact(dict(payload)),
        }
        with (self.run_dir / f"{stream}.jsonl").open("a", encoding="utf-8") as target:
            target.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
            target.flush()
```

`write_manifest` 必须把 `RunManifest` 序列化到临时文件，再用 `Path.replace()` 原子更新 `<run-dir>/manifest.json`。`redact` 递归处理字典和列表，键名命中 `authorization/api_key/token/password/contract_text/content/raw_response` 时写 `[REDACTED]`。事件文件永不以写入模式打开。

- [ ] **Step 4：忽略原始运行目录并验证**

在项目 `.gitignore` 增加：

```gitignore
# 本地硬指标原始证据，可能包含运行环境信息且体积较大
/evaluation-runs/
```

Run: `pytest tests/test_evaluation_evidence.py -q`

Expected: PASS；同名 `run-id` 第二次创建失败，两个事件都保留，敏感键被脱敏。

- [ ] **Step 5：提交证据核心**

```powershell
git add -- a03-contract-audit/.gitignore a03-contract-audit/backend/evaluation/evidence.py a03-contract-audit/backend/tests/test_evaluation_evidence.py
git commit -m "feat: add immutable evaluation evidence"
```

### Task 3：重构要素评测子命令

**Files:**
- Modify: `backend/evaluation/cli.py`
- Create: `backend/tests/test_evaluation_cli.py`
- Modify: `backend/tests/test_element_metrics.py`

- [ ] **Step 1：写要素命令成功、阈值未达和输入无效测试**

```python
def _write_jsonl(path: Path, rows: list[dict]) -> Path:
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    return path


def test_elements_command_returns_failed_when_f1_is_below_threshold(tmp_path):
    gold_row = _valid_gold_record()
    gold = _write_jsonl(tmp_path / "gold.jsonl", [gold_row])
    predictions = _write_jsonl(tmp_path / "predictions.jsonl", [{"case_id": "case-1", "prediction": {**gold_row["gold"], "party_b": "错误公司"}}])
    code = main([
        "elements", "--gold", str(gold), "--predictions", str(predictions),
        "--runs-root", str(tmp_path / "runs"), "--run-id", "elements-low",
        "--min-f1", "0.90",
    ])
    assert code == EXIT_FAILED


def test_elements_command_returns_invalid_for_bad_gold(tmp_path):
    gold_row = _valid_gold_record()
    gold_row["document_kind"] = "jpg"
    gold = _write_jsonl(tmp_path / "gold.jsonl", [gold_row])
    predictions = _write_jsonl(tmp_path / "predictions.jsonl", [{"case_id": "case-1", "prediction": gold_row["gold"]}])
    assert main(["elements", "--gold", str(gold), "--predictions", str(predictions), "--runs-root", str(tmp_path / "runs")]) == EXIT_INVALID
```

- [ ] **Step 2：运行测试确认旧 CLI 不支持子命令**

Run: `pytest tests/test_evaluation_cli.py -q`

Expected: FAIL，旧 `main()` 不接受参数列表或 `elements` 子命令。

- [ ] **Step 3：拆分 CLI 解析与执行并写入证据**

`main` 固定签名为 `main(argv: Sequence[str] | None = None) -> int`。创建子解析器：

```python
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="A03 硬指标证据流水线")
    subcommands = parser.add_subparsers(dest="command", required=True)
    elements = subcommands.add_parser("elements")
    elements.add_argument("--gold", type=Path, required=True)
    elements.add_argument("--predictions", type=Path, required=True)
    elements.add_argument("--runs-root", type=Path, default=Path("evaluation-runs"))
    elements.add_argument("--run-id")
    elements.add_argument("--min-f1", type=float, default=0.90)
    return parser
```

执行顺序固定为：读取并验证 JSONL、计算输入哈希、创建运行目录、写逐案例事件、写模块状态。`ValueError` 返回 `EXIT_INVALID`；F1 低于阈值返回 `EXIT_FAILED`；通过返回 `EXIT_OK`。预测集和报告不再写用户指定的任意散落文件，统一进入运行目录。

- [ ] **Step 4：运行 CLI 与要素回归测试**

Run: `pytest tests/test_evaluation_cli.py tests/test_element_metrics.py -q`

Expected: PASS；低分报告存在但状态为 `failed`，非法输入不产生 `passed`。

- [ ] **Step 5：提交要素命令**

```powershell
git add -- a03-contract-audit/backend/evaluation/cli.py a03-contract-audit/backend/tests/test_evaluation_cli.py a03-contract-audit/backend/tests/test_element_metrics.py
git commit -m "feat: add evidence-backed elements command"
```

### Task 4：实现 50+2 批量验收执行器

**Files:**
- Create: `backend/evaluation/batch.py`
- Create: `backend/tests/test_evaluation_batch.py`
- Modify: `backend/evaluation/cli.py`
- Modify: `backend/tests/test_evaluation_cli.py`

- [ ] **Step 1：写清单数量、有效批次、异常隔离和超时测试**

```python
@dataclass(frozen=True)
class FakeBatchGateway:
    terminal_status: str
    submission_sizes: list[int] = field(default_factory=list)

    def submit(self, samples, *, idempotency_key):
        self.submission_sizes.append(len(samples))
        if samples[0].role == "invalid":
            return BatchSubmission(batch_id=None, http_status=int(samples[0].expected_status), payload={})
        return BatchSubmission(batch_id=7, http_status=202, payload={})

    def get(self, batch_id):
        items = [{"status": "done"} for _ in range(50)] if self.terminal_status == "done" else [{"status": "running"} for _ in range(50)]
        return {"id": batch_id, "status": self.terminal_status, "total": 50, "items": items}


def make_manifest(tmp_path: Path, valid_count: int, invalid_count: int) -> Path:
    rows = []
    for index in range(valid_count):
        path = tmp_path / f"valid-{index}.txt"
        path.write_text("合同", encoding="utf-8")
        rows.append({"path": str(path), "role": "valid", "sha256": sha256_file(path), "expected_status": "done"})
    for index in range(invalid_count):
        path = tmp_path / f"invalid-{index}.exe"
        path.write_bytes(b"invalid")
        rows.append({"path": str(path), "role": "invalid", "sha256": sha256_file(path), "expected_status": 400})
    manifest = tmp_path / "batch-manifest.json"
    manifest.write_text(json.dumps({"schema_version": "1.0", "samples": rows}, ensure_ascii=False), encoding="utf-8")
    return manifest


def test_batch_manifest_requires_exactly_fifty_valid_and_two_invalid(tmp_path):
    manifest = make_manifest(tmp_path, valid_count=49, invalid_count=2)
    with pytest.raises(ValueError, match="50 个 valid"):
        load_batch_manifest(manifest)


def test_batch_runner_submits_valid_files_together_and_invalid_files_separately(tmp_path):
    gateway = FakeBatchGateway(terminal_status="done")
    result = run_batch_acceptance(load_batch_manifest(make_manifest(tmp_path, 50, 2)), gateway=gateway, poll_interval=0, timeout_seconds=5)
    assert gateway.submission_sizes == [50, 1, 1]
    assert result.status == "passed"


def test_batch_runner_times_out_without_infinite_polling(tmp_path):
    gateway = FakeBatchGateway(terminal_status="running")
    with pytest.raises(BatchTimeout, match="批次轮询超时"):
        run_batch_acceptance(load_batch_manifest(make_manifest(tmp_path, 50, 2)), gateway=gateway, poll_interval=0, timeout_seconds=0)
```

- [ ] **Step 2：运行测试确认执行器缺失**

Run: `pytest tests/test_evaluation_batch.py -q`

Expected: FAIL，提示 `evaluation.batch` 不存在。

- [ ] **Step 3：定义版本化清单和网关边界**

清单使用 JSON，样本结构固定为 `path/role/sha256/expected_status`。`role` 仅允许 `valid/invalid`；有效样本必须 50 个，异常样本必须 2 个。定义以下边界：

```python
@dataclass(frozen=True)
class BatchSample:
    path: Path
    role: Literal["valid", "invalid"]
    sha256: str
    expected_status: int | str


@dataclass(frozen=True)
class BatchSubmission:
    batch_id: int | None
    http_status: int
    payload: Mapping[str, Any]


class BatchTimeout(RuntimeError):
    """批次在验收总超时内没有进入终态。"""


class BatchGateway(Protocol):
    def submit(self, samples: Sequence[BatchSample], *, idempotency_key: str) -> BatchSubmission:
        raise NotImplementedError

    def get(self, batch_id: int) -> Mapping[str, Any]:
        raise NotImplementedError
```

`HttpBatchGateway` 使用现有 `httpx.Client`，从环境变量读取 Bearer token。上传时向 `/api/v1/batches` 发送文件句柄而非预先读取所有字节；不记录认证头和合同内容。

- [ ] **Step 4：实现执行状态流和追加事件**

`run_batch_acceptance` 必须按以下顺序执行：

```python
valid = [sample for sample in manifest.samples if sample.role == "valid"]
invalid = [sample for sample in manifest.samples if sample.role == "invalid"]
submission = gateway.submit(valid, idempotency_key=f"{run_id}-valid")
terminal = poll_until_terminal(
    gateway,
    submission.batch_id,
    deadline=deadline,
    on_event=lambda payload: writer.append("batch-events", payload),
)
invalid_results = [
    gateway.submit([sample], idempotency_key=f"{run_id}-invalid-{index}")
    for index, sample in enumerate(invalid, 1)
]
```

有效批次只有 `done` 且 50 个 item 全部 `done` 才通过。异常请求必须匹配清单声明的 HTTP 错误码或错误类别；任一异常文件被当成正常合同、有效批次出现失败、事件缺失或超时，状态均不得为 `passed`。完成后再次 GET，确认刷新恢复得到相同终态。

- [ ] **Step 5：接入 batch 子命令并验证**

增加参数：`--manifest`、`--base-url`、`--token-env`、`--poll-interval`、`--timeout-seconds`、`--runs-root`、`--run-id`。端点不可达返回 `EXIT_BLOCKED`；清单错误返回 `EXIT_INVALID`；验收未达返回 `EXIT_FAILED`。

Run: `pytest tests/test_evaluation_batch.py tests/test_evaluation_cli.py tests/test_batch_api.py tests/test_batch_service.py -q`

Expected: PASS，伪网关调用尺寸严格为 `[50, 1, 1]`，无无限轮询。

- [ ] **Step 6：提交批量执行器**

```powershell
git add -- a03-contract-audit/backend/evaluation/batch.py a03-contract-audit/backend/evaluation/cli.py a03-contract-audit/backend/tests/test_evaluation_batch.py a03-contract-audit/backend/tests/test_evaluation_cli.py
git commit -m "feat: add 50 plus 2 batch acceptance runner"
```

### Task 5：实现 OpenClaw/GPU 3+5 基准执行器

**Files:**
- Modify: `backend/evaluation/benchmark.py`
- Create: `backend/evaluation/benchmark_runner.py`
- Modify: `backend/tests/test_benchmark_stats.py`
- Create: `backend/tests/test_benchmark_runner.py`
- Modify: `backend/evaluation/cli.py`
- Modify: `backend/tests/test_evaluation_cli.py`

- [ ] **Step 1：写完整数据集轮次与不可比配置测试**

```python
@dataclass
class FakeTarget:
    callback: Callable[[str, BenchmarkCase], float]

    def invoke(self, phase: str, case: BenchmarkCase) -> InvocationResult:
        return InvocationResult(latency_ms=self.callback(phase, case), prompt_tokens=1, completion_tokens=1, error=None)


def test_runner_executes_three_warmups_and_five_measured_dataset_rounds():
    calls: list[tuple[str, str]] = []
    cases = [BenchmarkCase("case-1", "prompt-1"), BenchmarkCase("case-2", "prompt-2")]
    target = FakeTarget(lambda phase, case: calls.append((phase, case.case_id)) or 10.0)
    config = BenchmarkConfig(
        target="openclaw",
        model_sha256="model-hash",
        prompt_version="prompt-v1",
        dataset_sha256=dataset_sha256(cases),
        context_length=8192,
        concurrency=1,
        output_schema_sha256="schema-hash",
    )
    result = run_target(config, cases, target=target, writer=None)
    assert len([call for call in calls if call[0] == "warmup"]) == 6
    assert len([call for call in calls if call[0] == "measured"]) == 10
    assert result.measured_rounds == 5


def test_runner_rejects_dataset_with_hash_mismatch(tmp_path):
    manifest = tmp_path / "benchmark-manifest.json"
    manifest.write_text(json.dumps({"schema_version": "1.0", "dataset_sha256": "wrong", "cases": [{"case_id": "case-1", "prompt": "prompt-1"}]}), encoding="utf-8")
    with pytest.raises(ValueError, match="dataset_sha256"):
        load_benchmark_manifest(manifest)
```

- [ ] **Step 2：运行测试确认只有统计函数、没有执行器**

Run: `pytest tests/test_benchmark_stats.py tests/test_benchmark_runner.py -q`

Expected: FAIL，提示 `evaluation.benchmark_runner` 不存在或未强制轮次。

- [ ] **Step 3：收紧统计契约**

在 `benchmark.py` 中让汇总函数接收 `expected_runs`，数量不一致时拒绝报告：

```python
def summarize_benchmark(*, latencies_ms: Sequence[float | None], wall_seconds: float, expected_runs: int, power_samples: Sequence[PowerSample] | None = None) -> dict[str, object]:
    if len(latencies_ms) != expected_runs:
        raise ValueError(f"正式运行记录数量应为 {expected_runs}，实际为 {len(latencies_ms)}")
    if expected_runs <= 0:
        raise ValueError("expected_runs 必须大于 0")
    return _summarize_validated(latencies_ms, wall_seconds, power_samples)
```

更新现有测试，所有调用显式传入 `expected_runs`。保留能耗缺失时 `not_measured` 的既有行为。

- [ ] **Step 4：实现目标执行器与 3+5 完整轮次**

`benchmark_runner.py` 定义 `BenchmarkCase`、`InvocationResult`、`TargetSettings`、`OpenAICompatibleTarget`、`dataset_sha256` 和 `run_target(config, cases, *, target, writer)`。`writer` 允许在纯单元测试中传 `None`，真实 CLI 必须传 `EvidenceWriter`。每一轮遍历全部冻结样本；预热事件写入 JSONL 但不进入汇总：

```python
for round_index in range(config.warmup_runs):
    run_dataset_round("warmup", round_index, cases, target, writer)

measured: list[RoundResult] = []
for round_index in range(config.measured_runs):
    measured.append(run_dataset_round("measured", round_index, cases, target, writer))

if len(measured) != config.measured_runs:
    raise ValueError("正式轮次不完整")
```

目标通过 `/chat/completions` 调用，API key 从目标配置指定的环境变量读取。事件只保存 case ID、状态、延迟、token 数和错误类别，不保存 prompt、响应正文或认证信息。

- [ ] **Step 5：实现双目标公平性判定**

分别执行 OpenClaw 与 GPU 前调用 `assert_comparable`；配置哈希不一致立即返回输入无效。两端都完成后才生成比较结果。通过规则固定为：OpenClaw 成功率不低于 GPU，且 OpenClaw 的 P95 严格低于 GPU或吞吐量严格高于 GPU；两项均持平不算优于。没有功率样本时能耗保持 `not_measured`，不参与通过判定。

- [ ] **Step 6：接入 benchmark 子命令并验证**

增加参数：`--manifest`、`--openclaw-url`、`--openclaw-key-env`、`--gpu-url`、`--gpu-key-env`、`--runs-root`、`--run-id`。任一目标不可达返回 `EXIT_BLOCKED`；配置不可比返回 `EXIT_INVALID`；完整执行但 OpenClaw 未满足预声明标准返回 `EXIT_FAILED`。

Run: `pytest tests/test_benchmark_stats.py tests/test_benchmark_runner.py tests/test_evaluation_cli.py tests/test_runtime_status.py -q`

Expected: PASS；两个样本时每个目标发生 6 次预热调用和 10 次正式调用，原始事件不含 prompt 与响应正文。

- [ ] **Step 7：提交基准执行器**

```powershell
git add -- a03-contract-audit/backend/evaluation/benchmark.py a03-contract-audit/backend/evaluation/benchmark_runner.py a03-contract-audit/backend/evaluation/cli.py a03-contract-audit/backend/tests/test_benchmark_stats.py a03-contract-audit/backend/tests/test_benchmark_runner.py a03-contract-audit/backend/tests/test_evaluation_cli.py
git commit -m "feat: add reproducible runtime benchmark runner"
```

### Task 6：实现统一报告与防误报规则

**Files:**
- Create: `backend/evaluation/report.py`
- Create: `backend/tests/test_evaluation_report.py`
- Modify: `backend/evaluation/cli.py`
- Modify: `backend/tests/test_evaluation_cli.py`

- [ ] **Step 1：写缺事件、哈希冲突和状态聚合失败测试**

```python
def make_run(tmp_path: Path, modules: dict[str, str]) -> Path:
    run_dir = tmp_path / "run-1"
    run_dir.mkdir()
    manifest = {
        "schema_version": "1.0",
        "run_id": "run-1",
        "status": "error",
        "modules": modules,
        "inputs": {},
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    for name in ("elements", "batch-events", "benchmark"):
        (run_dir / f"{name}.jsonl").write_text(json.dumps({"schema_version": "1.0", "run_id": "run-1", "payload": {}}) + "\n", encoding="utf-8")
    return run_dir


def test_report_refuses_passed_when_required_stream_is_missing(tmp_path):
    run_dir = make_run(tmp_path, modules={"elements": "passed", "batch": "passed", "benchmark": "passed"})
    (run_dir / "batch-events.jsonl").unlink()
    with pytest.raises(InvalidEvidence, match="batch-events.jsonl"):
        build_report(run_dir)


@pytest.mark.parametrize(
    ("statuses", "overall"),
    [
        ({"elements": "passed", "batch": "passed", "benchmark": "passed"}, "passed"),
        ({"elements": "passed", "batch": "blocked", "benchmark": "passed"}, "blocked"),
        ({"elements": "failed", "batch": "blocked", "benchmark": "passed"}, "failed"),
        ({"elements": "error", "batch": "passed", "benchmark": "passed"}, "error"),
    ],
)
def test_report_status_precedence(statuses, overall):
    assert aggregate_status(statuses) == overall
```

- [ ] **Step 2：运行测试确认报告器缺失**

Run: `pytest tests/test_evaluation_report.py -q`

Expected: FAIL，提示 `evaluation.report` 不存在。

- [ ] **Step 3：实现证据完整性检查和 Markdown 生成**

状态优先级固定为 `error > failed > blocked > passed`。`build_report` 在汇总前校验 manifest 版本、run ID、输入哈希、必需事件流、元素样本数、批次 50+2 数量和基准 3+5 轮次。任何校验失败抛出 `InvalidEvidence`，CLI 返回 `EXIT_INVALID`。

报告固定包含：运行身份、环境、输入哈希、模块状态、指标结果、失败/阻塞原因和敏感信息声明。写入采用 UTF-8 和临时文件原子替换。

- [ ] **Step 4：增加 report 子命令并验证**

命令参数仅接受 `--run-dir`。报告写到该目录的 `report.md`；不能通过命令参数写到其他目录。

Run: `pytest tests/test_evaluation_report.py tests/test_evaluation_cli.py -q`

Expected: PASS；缺失或冲突证据无法生成 `passed`，报告中不存在认证头、合同正文和完整模型响应。

- [ ] **Step 5：提交报告器**

```powershell
git add -- a03-contract-audit/backend/evaluation/report.py a03-contract-audit/backend/evaluation/cli.py a03-contract-audit/backend/tests/test_evaluation_report.py a03-contract-audit/backend/tests/test_evaluation_cli.py
git commit -m "feat: prevent incomplete evaluation reports"
```

### Task 7：校准验收协议和硬指标矩阵

**Files:**
- Modify: `docs/evaluation/element-accuracy-protocol.md`
- Modify: `docs/evaluation/hard-indicator-matrix.md`

- [ ] **Step 1：更新要素协议**

将单个 `reviewer` 改为两个唯一 `reviewers`，说明 `agreed/adjudicated` 规则、未知预测 ID 拒绝、缺失预测计漏报，并更新复现命令：

```powershell
python -m evaluation.cli elements --gold data/gold.jsonl --predictions data/predictions.jsonl --runs-root evaluation-runs --run-id elements-20260901 --min-f1 0.90
```

- [ ] **Step 2：修正矩阵中的 PostgreSQL 证据等级**

将 PostgreSQL 当前状态由“已验证”改为“代码就绪待实测”，证据说明明确写出：现有烟雾测试使用 SQLite，只有在 PostgreSQL 16 完成空库迁移、回滚、再升级、数据核对与备份恢复后才能升级为“已验证”。

- [ ] **Step 3：写入三个真实验收命令但不伪造结果**

矩阵分别列出 `elements`、`batch`、`benchmark` 命令入口和所需外部条件。当前没有冻结 JSONL、52 文件集和硬件结果时，状态保持“阻塞”或“代码就绪待实测”。

- [ ] **Step 4：校验文档编码和差异**

Run: `rg -n "reviewer|PostgreSQL|SQLite|50.*2|预热.*3|正式.*5|blocked|阻塞" docs/evaluation backend/evaluation`

Expected: 协议与代码字段一致；不存在把 SQLite 测试描述成 PostgreSQL 已实测的句子。

Run: `git diff --check -- a03-contract-audit/docs/evaluation`

Expected: 退出码 0。

- [ ] **Step 5：提交协议与矩阵**

```powershell
git add -- a03-contract-audit/docs/evaluation/element-accuracy-protocol.md a03-contract-audit/docs/evaluation/hard-indicator-matrix.md
git commit -m "docs: align hard indicator evidence status"
```

### Task 8：全量回归、阻塞态演练与进度记录

**Files:**
- Modify: `PROGRESS.md`

- [ ] **Step 1：运行评测专项测试**

Run: `pytest tests/test_element_metrics.py tests/test_evaluation_evidence.py tests/test_evaluation_batch.py tests/test_benchmark_stats.py tests/test_benchmark_runner.py tests/test_evaluation_report.py tests/test_evaluation_cli.py -q`

Expected: 全部通过，0 failed。

- [ ] **Step 2：运行批次、OCR、权限和运行时回归**

Run: `pytest tests/test_batch_service.py tests/test_batch_api.py tests/test_parser_contracts.py tests/test_ocr_process.py tests/test_ocr_real_integration.py tests/test_audit_runner_quality.py tests/test_contract_quality_api.py tests/test_report_scope.py tests/test_runtime_status.py tests/test_hard_indicator_smoke.py -q`

Expected: 0 failed；环境型测试只允许带明确原因的 skip。

- [ ] **Step 3：运行后端全量测试**

Run: `pytest tests -q`

Expected: 0 failed；记录实际 passed、skipped、warnings 和耗时，不沿用历史数量。

- [ ] **Step 4：演练外部条件缺失时的阻塞状态**

使用不存在的本地端点和合法的最小测试清单调用批测与基准子命令，验证返回 `EXIT_BLOCKED=5`，manifest 和报告明确写出端点不可达，且不包含 token 值。该演练只验证阻塞语义，不得写入硬指标达标结论。

- [ ] **Step 5：检查证据目录未被 Git 跟踪**

Run: `git status --short --ignored -- a03-contract-audit/evaluation-runs`

Expected: 运行目录显示 `!!`，不显示 `A` 或 `??`。

- [ ] **Step 6：更新进度记录**

在 `PROGRESS.md` 顶部增加 `2026-09-01 · 硬指标证据流水线`，列出实际涉及文件、专项/全量测试结果、依赖审计结论，以及仍需真实数据、PostgreSQL、OpenClaw 和 GPU 环境执行的阻塞项。

- [ ] **Step 7：提交验证与进度记录**

```powershell
git add -- a03-contract-audit/PROGRESS.md
git commit -m "docs: record evidence pipeline verification"
```

- [ ] **Step 8：最终审查提交范围**

Run: `git status --short --branch`

Expected: 仅保留任务开始前已有的 `a03-contract-audit/outputs/` 未跟踪目录；不出现评测运行目录、密钥、合同文件或意外修改。

Run: `git log --oneline -8`

Expected: 可以逐项看到金标准、证据核心、要素命令、批测器、基准器、报告器、文档校准和进度记录提交。

## 真实环境验收门禁

本计划完成后，以下步骤仍需外部条件，不能由自动化测试替代：

| 优先级 | 外部条件 | 允许升级为“已验证”的证据 |
|---|---|---|
| P1 | 双人复核冻结金标准与真实预测 | 强校验通过、输入哈希固定、总体 F1 达到阈值 |
| P1 | 50 份有效文件和 2 份异常文件 | 有效同批完成、异常隔离、状态事件与资源记录齐全 |
| P1 | OpenClaw 与 GPU 对照环境 | 同配置 3+5 完整轮次、原始调用事件和比较报告 |
| P2 | Docker 与 PostgreSQL 16 | Compose 健康、迁移/回滚/再升级、数据核对、备份恢复 |

真实执行前必须再次确认数据不含未经授权的敏感合同，设备凭据只通过环境变量注入，运行目录不进入 Git。

## 计划自检结论

- 设计文档的要素校验、50+2、3+5、证据不可覆盖、失败语义、隐私边界和矩阵校准均有对应任务。
- 每个生产改动都排在失败测试之后，专项测试通过后才提交。
- 模块接口、状态名、退出状态和文件名在各任务中保持一致。
- 只引入一个新依赖 `jsonschema==4.25.1`，安装前设置了明确的安全审计与用户授权门禁。
- 不修改前端、CI/CD、Docker Compose、数据库模型和业务批次接口，不扩大阶段二范围。
- 全程使用当前主代理与 `superpowers:executing-plans`，不调用子代理。
