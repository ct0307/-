"""统一执行项目的本地开发质量门禁。"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import time
import urllib.error
import urllib.request
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


class GateError(RuntimeError):
    """质量门禁的环境或编排错误。"""


class LocalServiceManager:
    def __init__(
        self,
        config: GateConfig,
        *,
        ports: tuple[int, ...] = (8000, 5173),
        timeout_seconds: float = 30.0,
    ) -> None:
        self.config = config
        self.ports = ports
        self.timeout_seconds = timeout_seconds
        self.processes: list[subprocess.Popen] = []

    def ensure_ports_free(self) -> None:
        for port in self.ports:
            probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                probe.bind(("127.0.0.1", port))
            except OSError as exc:
                raise GateError(f"127.0.0.1:{port} 已被占用") from exc
            finally:
                probe.close()

    def start(self) -> None:
        backend = self.config.project_root / "backend"
        frontend = self.config.project_root / "frontend"
        commands = (
            (
                (
                    str(self.config.python_executable),
                    "-m",
                    "uvicorn",
                    "app.main:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    "8000",
                ),
                backend,
            ),
            (
                (
                    self.config.npm_executable,
                    "run",
                    "dev",
                    "--",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    "5173",
                    "--strictPort",
                ),
                frontend,
            ),
        )
        for argv, cwd in commands:
            self.processes.append(
                subprocess.Popen(
                    argv,
                    cwd=cwd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            )

    def wait_until_healthy(self) -> None:
        deadline = time.monotonic() + self.timeout_seconds
        urls = ("http://127.0.0.1:8000/health", "http://127.0.0.1:5173/login")
        pending = set(urls)
        while pending and time.monotonic() < deadline:
            for process in self.processes:
                if process.poll() is not None:
                    raise GateError(f"本地服务提前退出，退出码 {process.returncode}")
            for url in tuple(pending):
                try:
                    with urllib.request.urlopen(url, timeout=1) as response:
                        if 200 <= response.status < 400:
                            pending.remove(url)
                except (OSError, urllib.error.URLError):
                    pass
            if pending:
                time.sleep(0.25)
        if pending:
            raise GateError(f"本地服务健康检查超时：{', '.join(sorted(pending))}")

    def stop(self) -> None:
        for process in reversed(self.processes):
            if process.poll() is not None:
                continue
            if os.name == "nt":
                subprocess.run(
                    ("taskkill", "/PID", str(process.pid), "/T", "/F"),
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            else:  # pragma: no cover - 当前交付环境为 Windows
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
        self.processes.clear()


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
    started_at = clock()
    results: list[StepResult] = []
    status = "passed"
    exit_code = 0
    services_started = False
    try:
        if config.include_e2e:
            services.ensure_ports_free()
            services_started = True
            services.start()
            services.wait_until_healthy()
        for step in default_steps(config):
            result = runner.run(step)
            results.append(result)
            if result.exit_code != 0:
                status = "failed"
                exit_code = result.exit_code
                break
    except GateError as exc:
        print(f"质量门禁环境错误：{exc}")
        status = "failed"
        exit_code = 3
    except KeyboardInterrupt:
        status = "interrupted"
        exit_code = 130
    finally:
        if services_started:
            try:
                services.stop()
            except Exception as exc:  # pragma: no cover - 防止清理错误掩盖原始失败
                print(f"质量门禁服务回收失败：{exc}")
                status = "failed"
                exit_code = 3

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
