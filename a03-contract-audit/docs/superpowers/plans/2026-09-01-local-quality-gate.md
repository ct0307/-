# 本地一键质量门禁实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. 用户明确禁止子代理，全部任务由当前主代理顺序执行并在每次提交前自行审查。

**Goal:** 建立一个 Windows 一键入口，按固定顺序执行项目自动化验收、失败即停止、生成脱敏 JSON 汇总，并可选管理本地服务型 E2E 生命周期。

**Architecture:** `scripts/quality_gate.py` 提供可依赖注入的编排核心和 CLI，`scripts/quality_gate.ps1` 只负责定位后端虚拟环境并转发参数。默认模式不启动服务并清除前端子进程的 `E2E_BASE_URL`；可选 E2E 模式只管理自己创建的 uvicorn 与 Vite 进程。

**Tech Stack:** Python 3.11+ 标准库、pytest、PowerShell 5.1、Playwright、Vue TypeScript、Vite；不新增第三方依赖，不修改 CI/CD。

---

## 文件结构

| 路径 | 操作 | 单一职责 |
|---|---|---|
| `scripts/quality_gate.py` | 创建 | 步骤编排、命令执行、报告写入、健康检查和 E2E 进程管理 |
| `scripts/quality_gate.ps1` | 创建 | Windows 参数解析、虚拟环境定位和 Python CLI 调用 |
| `backend/tests/test_quality_gate.py` | 创建 | 编排、错误、报告、端口和 E2E 生命周期回归测试 |
| `.gitignore` | 修改 | 忽略 `/.quality-gate/` 本地运行报告 |
| `README.md` | 修改 | 使用方法、模式差异和证据边界 |
| `PROGRESS.md` | 修改 | 记录本轮实际验证证据和未实测边界 |

## 统一接口

```python
@dataclass(frozen=True)
class Step:
    name: str
    argv: tuple[str, ...]
    cwd: Path
    env_overrides: Mapping[str, str | None] = field(default_factory=dict)


@dataclass(frozen=True)
class StepResult:
    name: str
    status: Literal["passed", "failed"]
    exit_code: int
    duration_seconds: float


class CommandRunner(Protocol):
    def run(self, step: Step) -> StepResult: ...


def run_gate(
    config: GateConfig,
    *,
    runner: CommandRunner,
    services: ServiceManager,
    clock: Callable[[], datetime],
) -> int: ...
```

CLI 退出码固定为：成功 `0`、测试或构建返回原非零码、编排/环境/健康检查错误 `3`、用户中断 `130`。

### Task 1：默认步骤与失败即停止

**Files:**
- Create: `backend/tests/test_quality_gate.py`
- Create: `scripts/quality_gate.py`

- [ ] **Step 1：编写默认顺序和环境隔离失败测试**

测试通过 `importlib.util.spec_from_file_location` 从仓库 `scripts/quality_gate.py` 导入模块，避免修改 Python 包路径：

```python
def test_default_gate_runs_fixed_steps_and_clears_e2e_url(tmp_path):
    runner = RecordingRunner([0, 0, 0, 0, 0])
    code = quality_gate.run_gate(
        make_config(tmp_path),
        runner=runner,
        services=ForbiddenServices(),
        clock=fixed_clock,
    )
    assert code == 0
    assert [step.name for step in runner.steps] == [
        "evaluation", "backend", "frontend", "type-check", "build"
    ]
    frontend = next(step for step in runner.steps if step.name == "frontend")
    assert frontend.env_overrides["E2E_BASE_URL"] is None


def test_gate_stops_after_first_failed_step(tmp_path):
    runner = RecordingRunner([0, 7, 0, 0, 0])
    code = quality_gate.run_gate(
        make_config(tmp_path), runner=runner,
        services=ForbiddenServices(), clock=fixed_clock,
    )
    assert code == 7
    assert [step.name for step in runner.steps] == ["evaluation", "backend"]
```

- [ ] **Step 2：运行测试并确认红灯来自执行器缺失**

Run: `backend\.venv\Scripts\python.exe -m pytest backend/tests/test_quality_gate.py -q`

Expected: FAIL，提示 `scripts/quality_gate.py` 不存在。

- [ ] **Step 3：实现最小默认编排**

创建 `Step`、`StepResult`、`GateConfig`、`CommandRunner`、`default_steps()` 和 `run_gate()`。`default_steps()` 使用后端虚拟环境 Python，评测专项文件固定为：

```python
EVALUATION_TESTS = (
    "tests/test_element_metrics.py",
    "tests/test_evaluation_evidence.py",
    "tests/test_evaluation_batch.py",
    "tests/test_benchmark_stats.py",
    "tests/test_benchmark_runner.py",
    "tests/test_evaluation_report.py",
    "tests/test_evaluation_cli.py",
)
```

默认步骤依次构造：

```python
Step("evaluation", (python, "-m", "pytest", *EVALUATION_TESTS, "-q"), backend),
Step("backend", (python, "-m", "pytest", "tests", "-q"), backend),
Step("frontend", (npm, "test"), frontend, {"E2E_BASE_URL": None}),
Step("type-check", (npm, "run", "type-check"), frontend),
Step("build", (npm, "run", "build"), frontend),
```

`run_gate()` 顺序执行，首次非零立即返回，不调用后续步骤。

- [ ] **Step 4：运行专项测试并确认绿灯**

Run: `backend\.venv\Scripts\python.exe -m pytest backend/tests/test_quality_gate.py -q`

Expected: 当前两个测试 PASS。

- [ ] **Step 5：提交默认编排**

```powershell
git add -- a03-contract-audit/scripts/quality_gate.py a03-contract-audit/backend/tests/test_quality_gate.py
git commit -m "feat: add local quality gate orchestration"
```

### Task 2：原子 JSON 报告与真实命令执行

**Files:**
- Modify: `scripts/quality_gate.py`
- Modify: `backend/tests/test_quality_gate.py`

- [ ] **Step 1：编写成功、失败和中断报告测试**

```python
def test_gate_writes_atomic_summary_for_failure(tmp_path):
    code = quality_gate.run_gate(
        make_config(tmp_path), runner=RecordingRunner([0, 9]),
        services=ForbiddenServices(), clock=fixed_clock,
    )
    report = json.loads((tmp_path / ".quality-gate/summary.json").read_text("utf-8"))
    assert code == 9
    assert report["schema_version"] == 1
    assert report["status"] == "failed"
    assert report["exit_code"] == 9
    assert [step["name"] for step in report["steps"]] == ["evaluation", "backend"]
    assert not (tmp_path / ".quality-gate/summary.json.tmp").exists()


def test_gate_records_interruption_and_returns_130(tmp_path):
    code = quality_gate.run_gate(
        make_config(tmp_path), runner=InterruptingRunner(),
        services=ForbiddenServices(), clock=fixed_clock,
    )
    report = json.loads((tmp_path / ".quality-gate/summary.json").read_text("utf-8"))
    assert code == 130
    assert report["status"] == "interrupted"
```

- [ ] **Step 2：运行测试确认报告尚未生成**

Run: `backend\.venv\Scripts\python.exe -m pytest backend/tests/test_quality_gate.py -q`

Expected: 新测试 FAIL，提示 `summary.json` 不存在。

- [ ] **Step 3：实现报告和 subprocess 执行器**

实现 `SubprocessRunner`，基于 `os.environ.copy()` 应用覆盖：值为 `None` 时删除键，其余值写入子进程环境；使用 `subprocess.run(..., check=False)` 保持终端实时输出。

实现 `_write_summary()`：使用 UTC ISO-8601、当前 Git SHA、步骤状态和四舍五入到毫秒的耗时；写入同目录临时文件后 `Path.replace()`。`run_gate()` 在正常、失败和 `KeyboardInterrupt` 路径均写报告；报告写入失败返回 `3`。

- [ ] **Step 4：运行专项测试确认绿灯**

Run: `backend\.venv\Scripts\python.exe -m pytest backend/tests/test_quality_gate.py -q`

Expected: 所有当前测试 PASS。

- [ ] **Step 5：提交报告能力**

```powershell
git add -- a03-contract-audit/scripts/quality_gate.py a03-contract-audit/backend/tests/test_quality_gate.py
git commit -m "feat: record quality gate results"
```

### Task 3：可选 E2E 服务生命周期

**Files:**
- Modify: `scripts/quality_gate.py`
- Modify: `backend/tests/test_quality_gate.py`

- [ ] **Step 1：编写端口保护、健康检查和回收测试**

```python
def test_e2e_sets_url_and_stops_owned_services(tmp_path):
    services = RecordingServices()
    runner = RecordingRunner([0, 0, 0, 0, 0])
    code = quality_gate.run_gate(
        make_config(tmp_path, include_e2e=True), runner=runner,
        services=services, clock=fixed_clock,
    )
    frontend = next(step for step in runner.steps if step.name == "frontend")
    assert frontend.env_overrides["E2E_BASE_URL"] == "http://127.0.0.1:5173"
    assert services.events == ["ports", "start", "healthy", "stop"]
    assert code == 0


def test_e2e_stops_owned_services_when_frontend_tests_fail(tmp_path):
    services = RecordingServices()
    code = quality_gate.run_gate(
        make_config(tmp_path, include_e2e=True),
        runner=RecordingRunner([0, 0, 8]), services=services, clock=fixed_clock,
    )
    assert code == 8
    assert services.events[-1] == "stop"


def test_e2e_refuses_occupied_port_without_starting_services(tmp_path):
    services = OccupiedPortServices()
    code = quality_gate.run_gate(
        make_config(tmp_path, include_e2e=True),
        runner=RecordingRunner([]), services=services, clock=fixed_clock,
    )
    assert code == 3
    assert services.events == ["ports"]
```

- [ ] **Step 2：运行测试确认 E2E 生命周期尚未实现**

Run: `backend\.venv\Scripts\python.exe -m pytest backend/tests/test_quality_gate.py -q`

Expected: 新测试 FAIL，E2E 模式没有调用服务管理器。

- [ ] **Step 3：实现 ServiceManager 和本地服务管理**

定义协议方法 `ensure_ports_free()`、`start()`、`wait_until_healthy()`、`stop()`。真实实现：

- 使用 `socket.bind()` 检查 `127.0.0.1:8000/5173`，占用即抛出 `GateError`。
- 后端从 `backend` 目录启动虚拟环境 Python `-m uvicorn app.main:app --host 127.0.0.1 --port 8000`。
- 前端从 `frontend` 目录启动 `npm.cmd run dev -- --host 127.0.0.1 --port 5173 --strictPort`。
- 每 0.25 秒请求 `/health` 和 `/login`，最长 30 秒；子进程提前退出立即失败。
- Windows 使用记录的 PID 调用 `taskkill /PID <pid> /T /F`，其他平台使用新进程组终止；只处理自身创建的句柄。
- `run_gate()` 在 E2E 模式使用 `try/finally`，保证任何路径调用 `stop()`。

- [ ] **Step 4：运行专项测试确认绿灯**

Run: `backend\.venv\Scripts\python.exe -m pytest backend/tests/test_quality_gate.py -q`

Expected: 所有当前测试 PASS；失败和端口占用分支均无伪造步骤。

- [ ] **Step 5：提交 E2E 生命周期**

```powershell
git add -- a03-contract-audit/scripts/quality_gate.py a03-contract-audit/backend/tests/test_quality_gate.py
git commit -m "feat: manage optional quality gate e2e"
```

### Task 4：CLI、PowerShell 入口与前置校验

**Files:**
- Modify: `scripts/quality_gate.py`
- Create: `scripts/quality_gate.ps1`
- Modify: `backend/tests/test_quality_gate.py`

- [ ] **Step 1：编写 CLI 参数和缺失工具测试**

```python
def test_parse_args_accepts_include_e2e():
    assert quality_gate.parse_args(["--include-e2e"]).include_e2e is True


def test_preflight_reports_missing_backend_python(tmp_path):
    config = make_config(tmp_path)
    with pytest.raises(quality_gate.GateError, match="后端虚拟环境 Python"):
        quality_gate.validate_environment(config)
```

另用文本断言验证 PowerShell 入口包含 `param([switch]$IncludeE2E)`、后端虚拟环境绝对定位和 `$LASTEXITCODE` 透传。

- [ ] **Step 2：运行测试确认 CLI/入口缺失**

Run: `backend\.venv\Scripts\python.exe -m pytest backend/tests/test_quality_gate.py -q`

Expected: 新测试 FAIL，提示 `parse_args` 或 PowerShell 文件不存在。

- [ ] **Step 3：实现 CLI 与 PowerShell 薄入口**

Python CLI：

```python
def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="运行本地一键质量门禁")
    parser.add_argument("--include-e2e", action="store_true")
    return parser.parse_args(argv)
```

PowerShell 入口：

```powershell
[CmdletBinding()]
param([switch]$IncludeE2E)
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot 'backend\.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    Write-Error "未找到后端虚拟环境 Python：$python"
    exit 3
}
$arguments = @((Join-Path $PSScriptRoot 'quality_gate.py'))
if ($IncludeE2E) { $arguments += '--include-e2e' }
& $python @arguments
exit $LASTEXITCODE
```

`validate_environment()` 在执行任何步骤前校验仓库目录、虚拟环境 Python、`npm.cmd` 和 `frontend/node_modules`；不自动安装缺失依赖。

- [ ] **Step 4：运行专项测试确认绿灯**

Run: `backend\.venv\Scripts\python.exe -m pytest backend/tests/test_quality_gate.py -q`

Expected: 所有专项测试 PASS。

- [ ] **Step 5：提交可执行入口**

```powershell
git add -- a03-contract-audit/scripts/quality_gate.py a03-contract-audit/scripts/quality_gate.ps1 a03-contract-audit/backend/tests/test_quality_gate.py
git commit -m "feat: expose local quality gate command"
```

### Task 5：运行产物隔离与用户文档

**Files:**
- Modify: `.gitignore`
- Modify: `README.md`

- [ ] **Step 1：编写文档契约测试**

在 `test_quality_gate.py` 中读取文件并断言：

```python
def test_quality_gate_artifacts_are_ignored(repo_root):
    assert "/.quality-gate/" in (repo_root / ".gitignore").read_text("utf-8")


def test_readme_documents_modes_and_evidence_boundary(repo_root):
    readme = (repo_root / "README.md").read_text("utf-8")
    assert ".\\scripts\\quality_gate.ps1" in readme
    assert "-IncludeE2E" in readme
    assert "不等于真实硬指标验收" in readme
```

- [ ] **Step 2：运行测试确认文档契约红灯**

Run: `backend\.venv\Scripts\python.exe -m pytest backend/tests/test_quality_gate.py -q`

Expected: 新测试 FAIL，缺少忽略项和 README 说明。

- [ ] **Step 3：更新忽略规则和 README**

`.gitignore` 增加 `/.quality-gate/`。README 增加“本地一键质量门禁”章节，包含默认命令、可选 E2E 命令、执行阶段、失败即停止、报告路径和证据边界；明确不会自动安装依赖、不会修改 Git、不会替代真实 52 文件/数据库/硬件验收。

- [ ] **Step 4：运行专项测试确认绿灯并检查差异**

Run: `backend\.venv\Scripts\python.exe -m pytest backend/tests/test_quality_gate.py -q`

Expected: 所有专项测试 PASS。

Run: `git diff --check -- a03-contract-audit/.gitignore a03-contract-audit/README.md`

Expected: 退出码 0。

- [ ] **Step 5：提交文档与忽略规则**

```powershell
git add -- a03-contract-audit/.gitignore a03-contract-audit/README.md a03-contract-audit/backend/tests/test_quality_gate.py
git commit -m "docs: document local quality gate"
```

### Task 6：实际门禁验收与进度记录

**Files:**
- Modify: `PROGRESS.md`

- [ ] **Step 1：运行执行器专项测试**

Run: `backend\.venv\Scripts\python.exe -m pytest backend/tests/test_quality_gate.py -q`

Expected: 0 failed。

- [ ] **Step 2：实际运行默认一键门禁**

Run: `.\scripts\quality_gate.ps1`

Expected: 评测专项、后端全量、前端非服务测试、类型检查和生产构建全部通过；服务型 E2E 因无 `E2E_BASE_URL` 如实跳过；退出码 0。

- [ ] **Step 3：校验 JSON 报告和 Git 隔离**

Run: `Get-Content -LiteralPath '.quality-gate\summary.json' -Raw | ConvertFrom-Json | Format-List`

Expected: `schema_version=1`、`status=passed`、`exit_code=0`、五个步骤顺序正确。

Run: `git status --short --ignored -- .quality-gate outputs`

Expected: `.quality-gate/` 显示 `!!`；`outputs/` 仍保持原有未跟踪状态，没有被暂存或修改。

- [ ] **Step 4：更新进度记录**

在 `PROGRESS.md` 顶部增加本轮交付：实际提交文件、执行器专项数量、默认门禁五阶段真实结果、跳过的服务型 E2E 数量、类型检查/构建结果，以及未执行 `-IncludeE2E` 和真实硬指标验收的边界。

- [ ] **Step 5：提交验收记录**

```powershell
git add -- a03-contract-audit/PROGRESS.md
git commit -m "docs: record local quality gate verification"
```

- [ ] **Step 6：最终全量复核**

Run: `git status --short --branch`

Expected: 只保留任务开始前已有的 `a03-contract-audit/outputs/` 未跟踪目录。

Run: `git log --oneline -7`

Expected: 设计、计划、默认编排、报告、E2E 生命周期、入口、文档和验收记录均可追溯。

## 计划自检结论

- 设计中的默认模式、可选 E2E、失败即停止、原子 JSON、进程归属、前置校验、文档和证据边界均有对应任务。
- 每项生产行为前都有会因功能缺失而失败的测试，并要求记录红灯后才实现最小代码。
- `Step`、`StepResult`、`GateConfig`、`CommandRunner` 和 `ServiceManager` 名称在全部任务中保持一致。
- 不引入依赖，不修改 CI/CD、Docker、数据库、业务 API、前端页面或现有评测算法。
- 默认门禁会重复执行评测专项与后端全量，这是为报告分阶段定位而接受的明确成本。
- 全程由当前主代理使用 `executing-plans` 顺序执行，不调用子代理。
