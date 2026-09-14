import io
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from app.services.parser import ocr_worker
from app.services.parser import readiness
from app.services.parser.ocr import OCRResult
from app.services.parser.readiness import OCRReadiness, probe_ocr_runtime


class _Process:
    def __init__(
        self,
        stdout=b"",
        stderr=b"",
        returncode=0,
        timeout=False,
        terminate_timeout=False,
        pipe_error=False,
        cleanup_error=False,
    ):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode
        self.timeout = timeout
        self.terminate_timeout = terminate_timeout
        self.pipe_error = pipe_error
        self.cleanup_error = cleanup_error
        self.terminated = False
        self.killed = False
        self.calls = []

    def communicate(self, input=None, timeout=None):
        self.calls.append((input, timeout))
        if self.pipe_error and not self.terminated:
            raise RuntimeError("pipe failed")
        if self.timeout and not self.terminated:
            raise subprocess.TimeoutExpired("ocr-self-test", timeout)
        if self.terminate_timeout and self.terminated and not self.killed:
            raise subprocess.TimeoutExpired("ocr-self-test", timeout)
        if self.cleanup_error and self.terminated and not self.killed:
            raise RuntimeError("cleanup pipe failed")
        if self.killed:
            self.returncode = -9
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


@pytest.fixture(autouse=True)
def _clear_strict_probe_cache():
    reset = getattr(readiness, "_reset_strict_probe_cache", None)
    if reset is not None:
        reset()
    yield
    if reset is not None:
        reset()


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


def test_shallow_probe_reports_missing_onnxruntime_without_starting_worker(monkeypatch):
    def find_spec(name):
        return None if name == "onnxruntime" else object()

    monkeypatch.setattr("app.services.parser.readiness.importlib.util.find_spec", find_spec)
    monkeypatch.setattr(
        "app.services.parser.readiness.subprocess.Popen",
        lambda *_args, **_kwargs: pytest.fail("shallow probe must not start a worker"),
    )

    result = probe_ocr_runtime()

    assert result == OCRReadiness(False, "ocr_unavailable", "OCR 运行依赖不可用")


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


def test_strict_probe_uses_last_protocol_marker_and_ignores_worker_logs(monkeypatch):
    _dependencies_present(monkeypatch)
    process = _Process(
        b"engine initializing\nA03_OCR_SELF_TEST_V1={\"ready\":false}\n"
        b"engine done\nA03_OCR_SELF_TEST_V1={\"ready\":true,\"latency_ms\":5}\n"
    )
    monkeypatch.setattr("app.services.parser.readiness.subprocess.Popen", lambda *_args, **_kwargs: process)

    assert probe_ocr_runtime(strict=True) == OCRReadiness(ready=True, latency_ms=5)


def test_strict_probe_rejects_invalid_protocol_json(monkeypatch):
    _dependencies_present(monkeypatch)
    process = _Process(b"A03_OCR_SELF_TEST_V1={not json}\n")
    monkeypatch.setattr("app.services.parser.readiness.subprocess.Popen", lambda *_args, **_kwargs: process)

    assert probe_ocr_runtime(strict=True) == OCRReadiness(False, "ocr_self_test_failed", "OCR 自检失败")


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


def test_strict_probe_reaps_process_after_regular_pipe_error(monkeypatch):
    _dependencies_present(monkeypatch)
    process = _Process(returncode=None, pipe_error=True, cleanup_error=True)
    monkeypatch.setattr("app.services.parser.readiness.subprocess.Popen", lambda *_args, **_kwargs: process)

    result = probe_ocr_runtime(strict=True)

    assert result == OCRReadiness(False, "ocr_self_test_failed", "OCR 自检失败")
    assert process.terminated is True
    assert process.killed is True
    assert process.poll() is not None


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

    monkeypatch.setattr(ocr_worker, "_create_self_test_engine", lambda: Engine())
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

    monkeypatch.setattr(ocr_worker, "_create_self_test_engine", lambda: Engine())
    monkeypatch.setattr(ocr_worker.sys, "argv", ["ocr_worker", "--self-test"])
    stdout = io.BytesIO()
    monkeypatch.setattr(ocr_worker.sys, "stdout", type("Out", (), {"buffer": stdout})())

    assert ocr_worker.main() == 2
    assert stdout.getvalue() == b'A03_OCR_SELF_TEST_V1={"ready": false}\n'


def test_self_test_image_does_not_import_system_font_library(monkeypatch):
    monkeypatch.setitem(__import__("sys").modules, "PIL.ImageFont", None)

    assert ocr_worker._self_test_image().startswith(b"\x89PNG")


def test_offline_model_resolution_rejects_missing_model_without_downloading(monkeypatch, tmp_path):
    calls = []

    def network_request(*_args, **_kwargs):
        calls.append(True)
        raise AssertionError("network must not be used")

    from rapidocr.utils.download_file import DownloadFile

    monkeypatch.setattr(DownloadFile, "_make_http_request", classmethod(network_request))

    with pytest.raises(RuntimeError, match="本地模型"):
        ocr_worker._offline_rapidocr_params(model_dir=Path(tmp_path))

    assert calls == []


def test_offline_download_guard_blocks_rapidocr_download_entry(monkeypatch):
    calls = []

    def network_request(*_args, **_kwargs):
        calls.append(True)
        raise AssertionError("network must not be used")

    from rapidocr.utils.download_file import DownloadFile

    monkeypatch.setattr(DownloadFile, "_make_http_request", classmethod(network_request))
    with ocr_worker._block_rapidocr_downloads():
        with pytest.raises(RuntimeError, match="禁止联网"):
            DownloadFile._make_http_request("https://example.invalid", object())

    assert calls == []


def test_production_worker_uses_shared_offline_engine_factory(monkeypatch):
    engine = object()
    monkeypatch.setattr(ocr_worker, "create_offline_ocr_engine", lambda: engine)
    monkeypatch.setattr(
        ocr_worker,
        "_ocr_pdf_bytes_in_process",
        lambda data, *, engine, **_kwargs: OCRResult("ok", 1, 1.0),
    )
    monkeypatch.setattr(
        ocr_worker.sys,
        "stdin",
        type("Input", (), {"buffer": io.BytesIO(b"not a real pdf")})(),
    )
    monkeypatch.setattr(
        ocr_worker.sys,
        "argv",
        [
            "ocr_worker",
            "--max-pages", "1",
            "--max-page-pixels", "1",
            "--dpi", "36",
            "--timeout-seconds", "1",
            "--min-confidence", "0",
        ],
    )
    stdout = io.BytesIO()
    monkeypatch.setattr(ocr_worker.sys, "stdout", type("Output", (), {"buffer": stdout})())

    assert ocr_worker.main() == 0
    assert b'A03_OCR_RESULT_V1={"ok": true' in stdout.getvalue()


def test_shared_offline_factory_rejects_missing_model_before_any_download(monkeypatch, tmp_path):
    from app.services.parser import ocr
    from rapidocr.utils.download_file import DownloadFile

    calls = []
    monkeypatch.setattr(
        DownloadFile,
        "_make_http_request",
        classmethod(lambda *_args, **_kwargs: calls.append(True)),
    )

    with pytest.raises(RuntimeError, match="本地模型"):
        ocr.create_offline_ocr_engine(model_dir=Path(tmp_path))

    assert calls == []


def test_strict_probe_single_flight_and_caches_failed_result(monkeypatch):
    _dependencies_present(monkeypatch)
    started = threading.Event()
    release = threading.Event()
    calls = []

    def slow_failed_probe():
        calls.append(True)
        started.set()
        assert release.wait(timeout=2)
        return OCRReadiness(False, "ocr_self_test_failed", "OCR 自检失败")

    monkeypatch.setattr(readiness, "_probe_ocr_self_test", slow_failed_probe)
    results = []
    first = threading.Thread(target=lambda: results.append(probe_ocr_runtime(strict=True)))
    second = threading.Thread(target=lambda: results.append(probe_ocr_runtime(strict=True)))

    first.start()
    assert started.wait(timeout=1)
    second.start()
    release.set()
    first.join(timeout=2)
    second.join(timeout=2)

    assert calls == [True]
    assert results == [
        OCRReadiness(False, "ocr_self_test_failed", "OCR 自检失败"),
        OCRReadiness(False, "ocr_self_test_failed", "OCR 自检失败"),
    ]
    assert probe_ocr_runtime(strict=True) == results[0]
    assert calls == [True]
    assert probe_ocr_runtime(strict=False) == OCRReadiness(True)


@pytest.mark.parametrize("interrupt", (KeyboardInterrupt, SystemExit))
def test_strict_probe_reaps_and_reraises_process_interrupt(monkeypatch, interrupt):
    _dependencies_present(monkeypatch)

    class InterruptProcess(_Process):
        def communicate(self, input=None, timeout=None):
            self.calls.append((input, timeout))
            if not self.terminated:
                raise interrupt()
            self.returncode = 0
            return b"", b""

    process = InterruptProcess(returncode=None)
    monkeypatch.setattr(readiness.subprocess, "Popen", lambda *_args, **_kwargs: process)

    with pytest.raises(interrupt):
        probe_ocr_runtime(strict=True)

    assert process.terminated is True
    assert process.poll() == 0


def test_real_worker_self_test_blocks_all_network_attempts(monkeypatch):
    environment = os.environ.copy()
    environment["A03_OCR_SELF_TEST_BLOCK_NETWORK"] = "1"
    completed = subprocess.run(
        [sys.executable, "-m", "app.services.parser.ocr_worker", "--self-test"],
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        capture_output=True,
        timeout=20,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr.decode("utf-8", errors="replace")
    line = next(
        item
        for item in completed.stdout.splitlines()
        if item.startswith(b"A03_OCR_SELF_TEST_V1=")
    )
    payload = json.loads(line.removeprefix(b"A03_OCR_SELF_TEST_V1=").decode("utf-8"))
    assert payload["ready"] is True
    assert payload["network_attempts"] == 0
