import subprocess
import sys
import time

import pytest

from app.services.parser.ocr import (
    OCRError,
    OCRTimeout,
    _communicate_with_timeout,
    _parse_worker_result,
)


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


class _FakeProcess:
    def __init__(self, communicate_results):
        self._communicate_results = iter(communicate_results)
        self.returncode = None
        self.terminated = False
        self.killed = False

    def communicate(self, *args, **kwargs):
        result = next(self._communicate_results)
        if isinstance(result, BaseException):
            raise result
        self.returncode = 0
        return result

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True


def test_child_process_is_reaped_when_communicate_raises_regular_exception():
    process = _FakeProcess((RuntimeError("pipe failed"), (b"", b"")))

    with pytest.raises(RuntimeError, match="pipe failed"):
        _communicate_with_timeout(process, b"pdf", timeout_seconds=1)

    assert process.terminated is True
    assert process.poll() is not None


def test_child_process_is_killed_when_terminate_does_not_finish():
    process = _FakeProcess(
        (
            subprocess.TimeoutExpired("ocr", 1),
            subprocess.TimeoutExpired("ocr", 2),
            (b"", b""),
        )
    )

    with pytest.raises(OCRTimeout):
        _communicate_with_timeout(process, b"pdf", timeout_seconds=1)

    assert process.terminated is True
    assert process.killed is True
    assert process.poll() is not None


def test_worker_protocol_maps_structured_unavailable_error():
    payload = (
        b'A03_OCR_RESULT_V1={"ok":false,"error_type":"OCRUnavailable",'
        b'"message":"model missing"}\n'
    )

    from app.services.parser.ocr import OCRUnavailable

    with pytest.raises(OCRUnavailable, match="model missing"):
        _parse_worker_result(payload)
