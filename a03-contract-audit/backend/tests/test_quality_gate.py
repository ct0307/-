"""本地质量门禁必须按固定顺序执行，并在失败时立即停止。"""

import importlib.util
import json
import socket
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = PROJECT_ROOT / "scripts" / "quality_gate.py"
SPEC = importlib.util.spec_from_file_location("quality_gate", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
quality_gate = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = quality_gate
SPEC.loader.exec_module(quality_gate)


class RecordingRunner:
    def __init__(self, exit_codes: list[int]):
        self.exit_codes = iter(exit_codes)
        self.steps = []

    def run(self, step):
        self.steps.append(step)
        exit_code = next(self.exit_codes)
        return quality_gate.StepResult(
            name=step.name,
            status="passed" if exit_code == 0 else "failed",
            exit_code=exit_code,
            duration_seconds=0.1,
        )


class ForbiddenServices:
    def ensure_ports_free(self):
        raise AssertionError("默认门禁不得检查服务端口")

    def start(self):
        raise AssertionError("默认门禁不得启动服务")

    def wait_until_healthy(self):
        raise AssertionError("默认门禁不得等待服务")

    def stop(self):
        raise AssertionError("默认门禁不得停止服务")


class InterruptingRunner:
    def run(self, step):
        raise KeyboardInterrupt


class RecordingServices:
    def __init__(self):
        self.events = []

    def ensure_ports_free(self):
        self.events.append("ports")

    def start(self):
        self.events.append("start")

    def wait_until_healthy(self):
        self.events.append("healthy")

    def stop(self):
        self.events.append("stop")


class OccupiedPortServices(RecordingServices):
    def ensure_ports_free(self):
        self.events.append("ports")
        raise quality_gate.GateError("端口已占用")


def fixed_clock():
    return datetime(2026, 9, 1, tzinfo=timezone.utc)


def make_config(tmp_path: Path, *, include_e2e: bool = False):
    return quality_gate.GateConfig(
        project_root=tmp_path,
        python_executable=tmp_path / "backend/.venv/Scripts/python.exe",
        npm_executable="npm.cmd",
        include_e2e=include_e2e,
    )


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
        "evaluation",
        "backend",
        "frontend",
        "type-check",
        "build",
    ]
    frontend = next(step for step in runner.steps if step.name == "frontend")
    assert frontend.env_overrides["E2E_BASE_URL"] is None


def test_gate_stops_after_first_failed_step(tmp_path):
    runner = RecordingRunner([0, 7, 0, 0, 0])

    code = quality_gate.run_gate(
        make_config(tmp_path),
        runner=runner,
        services=ForbiddenServices(),
        clock=fixed_clock,
    )

    assert code == 7
    assert [step.name for step in runner.steps] == ["evaluation", "backend"]


def test_gate_writes_atomic_summary_for_failure(tmp_path):
    code = quality_gate.run_gate(
        make_config(tmp_path),
        runner=RecordingRunner([0, 9]),
        services=ForbiddenServices(),
        clock=fixed_clock,
    )

    report = json.loads(
        (tmp_path / ".quality-gate/summary.json").read_text(encoding="utf-8")
    )
    assert code == 9
    assert report["schema_version"] == 1
    assert report["status"] == "failed"
    assert report["exit_code"] == 9
    assert [step["name"] for step in report["steps"]] == ["evaluation", "backend"]
    assert not (tmp_path / ".quality-gate/summary.json.tmp").exists()


def test_gate_records_interruption_and_returns_130(tmp_path):
    code = quality_gate.run_gate(
        make_config(tmp_path),
        runner=InterruptingRunner(),
        services=ForbiddenServices(),
        clock=fixed_clock,
    )

    report = json.loads(
        (tmp_path / ".quality-gate/summary.json").read_text(encoding="utf-8")
    )
    assert code == 130
    assert report["status"] == "interrupted"
    assert report["exit_code"] == 130


def test_e2e_sets_url_and_stops_owned_services(tmp_path):
    services = RecordingServices()
    runner = RecordingRunner([0, 0, 0, 0, 0])

    code = quality_gate.run_gate(
        make_config(tmp_path, include_e2e=True),
        runner=runner,
        services=services,
        clock=fixed_clock,
    )

    frontend = next(step for step in runner.steps if step.name == "frontend")
    assert frontend.env_overrides["E2E_BASE_URL"] == "http://127.0.0.1:5173"
    assert services.events == ["ports", "start", "healthy", "stop"]
    assert code == 0


def test_e2e_stops_owned_services_when_frontend_tests_fail(tmp_path):
    services = RecordingServices()

    code = quality_gate.run_gate(
        make_config(tmp_path, include_e2e=True),
        runner=RecordingRunner([0, 0, 8]),
        services=services,
        clock=fixed_clock,
    )

    assert code == 8
    assert services.events[-1] == "stop"


def test_e2e_refuses_occupied_port_without_starting_services(tmp_path):
    services = OccupiedPortServices()

    code = quality_gate.run_gate(
        make_config(tmp_path, include_e2e=True),
        runner=RecordingRunner([]),
        services=services,
        clock=fixed_clock,
    )

    assert code == 3
    assert services.events == ["ports"]


def test_local_services_reject_an_occupied_port(tmp_path):
    held = socket.socket()
    held.bind(("127.0.0.1", 0))
    port = held.getsockname()[1]
    manager = quality_gate.LocalServiceManager(
        make_config(tmp_path, include_e2e=True),
        ports=(port,),
    )
    try:
        try:
            manager.ensure_ports_free()
        except quality_gate.GateError as exc:
            assert str(port) in str(exc)
        else:
            raise AssertionError("占用端口必须阻止 E2E 启动")
    finally:
        held.close()


def test_local_services_stop_only_recorded_processes(monkeypatch, tmp_path):
    commands = []

    class Process:
        def __init__(self, pid):
            self.pid = pid

        def poll(self):
            return None

    monkeypatch.setattr(quality_gate.os, "name", "nt")
    monkeypatch.setattr(
        quality_gate.subprocess,
        "run",
        lambda argv, **kwargs: commands.append((tuple(argv), kwargs)),
    )
    manager = quality_gate.LocalServiceManager(
        make_config(tmp_path, include_e2e=True)
    )
    manager.processes = [Process(101), Process(202)]

    manager.stop()

    assert [command[0] for command in commands] == [
        ("taskkill", "/PID", "202", "/T", "/F"),
        ("taskkill", "/PID", "101", "/T", "/F"),
    ]


def test_parse_args_accepts_include_e2e():
    assert quality_gate.parse_args(["--include-e2e"]).include_e2e is True


def test_preflight_reports_missing_backend_python(tmp_path):
    with pytest.raises(quality_gate.GateError, match="后端虚拟环境 Python"):
        quality_gate.validate_environment(make_config(tmp_path))


def test_subprocess_runner_removes_overridden_environment(monkeypatch, tmp_path):
    captured = {}

    class Completed:
        returncode = 0

    def fake_run(argv, **kwargs):
        captured["argv"] = tuple(argv)
        captured.update(kwargs)
        return Completed()

    monkeypatch.setenv("E2E_BASE_URL", "http://stale.example")
    monkeypatch.setattr(quality_gate.subprocess, "run", fake_run)
    runner = quality_gate.SubprocessRunner(monotonic=lambda: 10.0)

    result = runner.run(
        quality_gate.Step(
            "frontend",
            ("npm.cmd", "test"),
            tmp_path,
            {"E2E_BASE_URL": None},
        )
    )

    assert result.exit_code == 0
    assert "E2E_BASE_URL" not in captured["env"]
    assert captured["cwd"] == tmp_path
    assert captured["check"] is False


def test_powershell_entry_forwards_switch_and_exit_code():
    script = (PROJECT_ROOT / "scripts/quality_gate.ps1").read_text(encoding="utf-8")
    assert "param([switch]$IncludeE2E)" in script
    assert "backend\\.venv\\Scripts\\python.exe" in script
    assert "--include-e2e" in script
    assert "exit $LASTEXITCODE" in script


def test_report_timestamps_are_normalized_to_utc():
    local_time = datetime(2026, 9, 1, 20, 0, tzinfo=timezone(timedelta(hours=8)))

    assert quality_gate._iso_utc(local_time) == "2026-09-01T12:00:00Z"
