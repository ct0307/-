"""统一执行项目的本地开发质量门禁。"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Literal, Mapping, Protocol


EVALUATION_TESTS = (
    "tests/test_element_metrics.py",
    "tests/test_evaluation_evidence.py",
    "tests/test_evaluation_batch.py",
    "tests/test_benchmark_stats.py",
    "tests/test_benchmark_runner.py",
    "tests/test_evaluation_report.py",
    "tests/test_evaluation_cli.py",
)


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


@dataclass(frozen=True)
class GateConfig:
    project_root: Path
    python_executable: Path
    npm_executable: str
    include_e2e: bool = False


class CommandRunner(Protocol):
    def run(self, step: Step) -> StepResult: ...


class ServiceManager(Protocol):
    def ensure_ports_free(self) -> None: ...

    def start(self) -> None: ...

    def wait_until_healthy(self) -> None: ...

    def stop(self) -> None: ...


def default_steps(config: GateConfig) -> tuple[Step, ...]:
    backend = config.project_root / "backend"
    frontend = config.project_root / "frontend"
    python = str(config.python_executable)
    npm = config.npm_executable
    e2e_url = "http://127.0.0.1:5173" if config.include_e2e else None
    return (
        Step(
            "evaluation",
            (python, "-m", "pytest", *EVALUATION_TESTS, "-q"),
            backend,
        ),
        Step("backend", (python, "-m", "pytest", "tests", "-q"), backend),
        Step("frontend", (npm, "test"), frontend, {"E2E_BASE_URL": e2e_url}),
        Step("type-check", (npm, "run", "type-check"), frontend),
        Step("build", (npm, "run", "build"), frontend),
    )


def run_gate(
    config: GateConfig,
    *,
    runner: CommandRunner,
    services: ServiceManager,
    clock: Callable[[], datetime],
) -> int:
    del services
    started_at = clock()
    results: list[StepResult] = []
    status = "passed"
    exit_code = 0
    try:
        for step in default_steps(config):
            result = runner.run(step)
            results.append(result)
            if result.exit_code != 0:
                status = "failed"
                exit_code = result.exit_code
                break
    except KeyboardInterrupt:
        status = "interrupted"
        exit_code = 130

    try:
        _write_summary(
            config,
            started_at=started_at,
            finished_at=clock(),
            status=status,
            exit_code=exit_code,
            results=results,
        )
    except OSError as exc:
        print(f"质量门禁报告写入失败：{exc}")
        return 3
    return exit_code


def _git_commit(project_root: Path) -> str:
    completed = subprocess.run(
        ("git", "rev-parse", "HEAD"),
        cwd=project_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        return "unknown"
    return completed.stdout.strip() or "unknown"


def _iso_utc(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _write_summary(
    config: GateConfig,
    *,
    started_at: datetime,
    finished_at: datetime,
    status: str,
    exit_code: int,
    results: list[StepResult],
) -> None:
    report_dir = config.project_root / ".quality-gate"
    report_dir.mkdir(parents=True, exist_ok=True)
    target = report_dir / "summary.json"
    temporary = report_dir / "summary.json.tmp"
    payload = {
        "schema_version": 1,
        "mode": "e2e" if config.include_e2e else "default",
        "git_commit": _git_commit(config.project_root),
        "started_at": _iso_utc(started_at),
        "finished_at": _iso_utc(finished_at),
        "status": status,
        "exit_code": exit_code,
        "steps": [
            {
                "name": result.name,
                "status": result.status,
                "exit_code": result.exit_code,
                "duration_seconds": round(result.duration_seconds, 3),
            }
            for result in results
        ],
    }
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(target)
