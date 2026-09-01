"""统一执行项目的本地开发质量门禁。"""

from __future__ import annotations

from dataclasses import dataclass, field
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
    clock: Callable[[], object],
) -> int:
    del services, clock
    for step in default_steps(config):
        result = runner.run(step)
        if result.exit_code != 0:
            return result.exit_code
    return 0
