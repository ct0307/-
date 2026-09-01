"""本地质量门禁必须按固定顺序执行，并在失败时立即停止。"""

import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


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


def fixed_clock():
    return datetime(2026, 9, 1, tzinfo=timezone.utc)


def make_config(tmp_path: Path):
    return quality_gate.GateConfig(
        project_root=tmp_path,
        python_executable=tmp_path / "backend/.venv/Scripts/python.exe",
        npm_executable="npm.cmd",
        include_e2e=False,
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
