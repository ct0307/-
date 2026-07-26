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
