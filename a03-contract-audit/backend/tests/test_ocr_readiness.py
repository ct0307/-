import io
import subprocess

import pytest

from app.services.parser import ocr_worker
from app.services.parser.readiness import OCRReadiness, probe_ocr_runtime


class _Process:
    def __init__(self, stdout=b"", stderr=b"", returncode=0, timeout=False, terminate_timeout=False):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode
        self.timeout = timeout
        self.terminate_timeout = terminate_timeout
        self.terminated = False
        self.killed = False
        self.calls = []

    def communicate(self, input=None, timeout=None):
        self.calls.append((input, timeout))
        if self.timeout and not self.terminated:
            raise subprocess.TimeoutExpired("ocr-self-test", timeout)
        if self.terminate_timeout and self.terminated and not self.killed:
            raise subprocess.TimeoutExpired("ocr-self-test", timeout)
        return self.stdout, self.stderr

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True


def _dependencies_present(monkeypatch):
    monkeypatch.setattr(
        "app.services.parser.readiness.importlib.util.find_spec", lambda _name: object()
    )


def test_readiness_is_frozen_and_serializable():
    result = OCRReadiness(ready=True, latency_ms=12)

    assert result.to_dict() == {"ready": True, "latency_ms": 12}
    with pytest.raises(AttributeError):
        result.ready = False


def test_shallow_probe_reports_missing_dependency_without_loading_model(monkeypatch):
    calls = []

    def find_spec(name):
        calls.append(name)
        return None if name == "rapidocr" else object()

    monkeypatch.setattr("app.services.parser.readiness.importlib.util.find_spec", find_spec)
    monkeypatch.setattr(
        "app.services.parser.readiness.subprocess.Popen",
        lambda *_args, **_kwargs: pytest.fail("shallow probe must not start a worker"),
    )

    result = probe_ocr_runtime()

    assert result.ready is False
    assert result.error_code == "ocr_unavailable"
    assert result.detail == "OCR 运行依赖不可用"
    assert calls == ["rapidocr"]


def test_shallow_probe_does_not_load_model_when_dependencies_exist(monkeypatch):
    _dependencies_present(monkeypatch)
    monkeypatch.setattr(
        "app.services.parser.readiness.subprocess.Popen",
        lambda *_args, **_kwargs: pytest.fail("shallow probe must not start a worker"),
    )

    assert probe_ocr_runtime() == OCRReadiness(ready=True)


def test_strict_probe_runs_self_test_and_parses_fixed_protocol(monkeypatch):
    _dependencies_present(monkeypatch)
    process = _Process(b'A03_OCR_SELF_TEST_V1={"ready":true,"latency_ms":9}\n')
    commands = []
    monkeypatch.setattr(
        "app.services.parser.readiness.subprocess.Popen",
        lambda command, **kwargs: commands.append((command, kwargs)) or process,
    )

    result = probe_ocr_runtime(strict=True)

    assert result == OCRReadiness(ready=True, latency_ms=9)
    assert commands[0][0][-1:] == ["--self-test"]
    assert process.calls == [(b"", 20)]


def test_strict_probe_maps_startup_failure_to_unavailable(monkeypatch):
    _dependencies_present(monkeypatch)
    monkeypatch.setattr(
        "app.services.parser.readiness.subprocess.Popen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("not executable")),
    )

    result = probe_ocr_runtime(strict=True)

    assert result == OCRReadiness(False, "ocr_unavailable", "OCR 自检进程无法启动")


def test_strict_probe_times_out_and_reaps_process(monkeypatch):
    _dependencies_present(monkeypatch)
    process = _Process(timeout=True, terminate_timeout=True, returncode=None)
    monkeypatch.setattr("app.services.parser.readiness.subprocess.Popen", lambda *_args, **_kwargs: process)

    result = probe_ocr_runtime(strict=True)

    assert result == OCRReadiness(False, "ocr_self_test_timeout", "OCR 自检超时")
    assert process.terminated is True
    assert process.killed is True
    assert len(process.calls) == 3


@pytest.mark.parametrize(
    ("stdout", "returncode"),
    [
        (b"unexpected output\n", 0),
        (b'A03_OCR_SELF_TEST_V1={"ready":false}\n', 0),
        (b'A03_OCR_SELF_TEST_V1={"ready":true}\n', 3),
    ],
)
def test_strict_probe_rejects_invalid_or_failed_response(monkeypatch, stdout, returncode):
    _dependencies_present(monkeypatch)
    monkeypatch.setattr(
        "app.services.parser.readiness.subprocess.Popen",
        lambda *_args, **_kwargs: _Process(stdout=stdout, stderr=b"model internals", returncode=returncode),
    )

    result = probe_ocr_runtime(strict=True)

    assert result == OCRReadiness(False, "ocr_self_test_failed", "OCR 自检失败")
    assert "internals" not in (result.detail or "")


def test_worker_self_test_uses_in_memory_image_and_does_not_read_stdin(monkeypatch):
    class Engine:
        def recognize(self, image):
            assert image
            return "CONTRACT 10000", 0.99

    monkeypatch.setattr(ocr_worker, "RapidOCREngine", Engine)
    monkeypatch.setattr(ocr_worker.sys, "stdin", type("BlockedStdin", (), {"buffer": type("B", (), {"read": lambda self: pytest.fail("stdin read")})()})())
    monkeypatch.setattr(ocr_worker.sys, "argv", ["ocr_worker", "--self-test"])
    stdout = io.BytesIO()
    monkeypatch.setattr(ocr_worker.sys, "stdout", type("Out", (), {"buffer": stdout})())

    assert ocr_worker.main() == 0
    assert stdout.getvalue().startswith(b"A03_OCR_SELF_TEST_V1=")
    assert b'"ready": true' in stdout.getvalue()


def test_worker_self_test_reports_recognition_failure_with_fixed_protocol(monkeypatch):
    class Engine:
        def recognize(self, image):
            return "other text", 0.99

    monkeypatch.setattr(ocr_worker, "RapidOCREngine", Engine)
    monkeypatch.setattr(ocr_worker.sys, "argv", ["ocr_worker", "--self-test"])
    stdout = io.BytesIO()
    monkeypatch.setattr(ocr_worker.sys, "stdout", type("Out", (), {"buffer": stdout})())

    assert ocr_worker.main() == 2
    assert stdout.getvalue() == b'A03_OCR_SELF_TEST_V1={"ready": false}\n'
