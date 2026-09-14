"""OCR 运行时就绪探测，严格模式通过隔离子进程验证真实识别链路。"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import importlib.util
import json
import subprocess
import sys


_SELF_TEST_PREFIX = b"A03_OCR_SELF_TEST_V1="
_SELF_TEST_TIMEOUT_SECONDS = 20


@dataclass(frozen=True)
class OCRReadiness:
    ready: bool
    error_code: str | None = None
    detail: str | None = None
    latency_ms: int | None = None

    def to_dict(self) -> dict[str, object]:
        return {key: value for key, value in asdict(self).items() if value is not None}


def probe_ocr_runtime(*, strict: bool = False) -> OCRReadiness:
    """检查 OCR 依赖；严格模式会在隔离进程中执行固定图像自检。"""
    if importlib.util.find_spec("rapidocr") is None or importlib.util.find_spec("onnxruntime") is None:
        return OCRReadiness(False, "ocr_unavailable", "OCR 运行依赖不可用")
    if not strict:
        return OCRReadiness(True)
    return _probe_ocr_self_test()


def _probe_ocr_self_test() -> OCRReadiness:
    try:
        process = subprocess.Popen(
            [sys.executable, "-m", "app.services.parser.ocr_worker", "--self-test"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError:
        return OCRReadiness(False, "ocr_unavailable", "OCR 自检进程无法启动")

    try:
        stdout, _stderr = process.communicate(input=b"", timeout=_SELF_TEST_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        _terminate_and_reap(process)
        return OCRReadiness(False, "ocr_self_test_timeout", "OCR 自检超时")
    except BaseException:
        _terminate_and_reap(process)
        return OCRReadiness(False, "ocr_self_test_failed", "OCR 自检失败")

    if process.returncode not in (0, None):
        return OCRReadiness(False, "ocr_self_test_failed", "OCR 自检失败")
    return _parse_self_test_result(stdout)


def _terminate_and_reap(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        process.terminate()
        try:
            process.communicate(timeout=2)
            return
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
    except BaseException:
        return


def _parse_self_test_result(stdout: bytes) -> OCRReadiness:
    lines = stdout.splitlines()
    if len(lines) != 1 or not lines[0].startswith(_SELF_TEST_PREFIX):
        return OCRReadiness(False, "ocr_self_test_failed", "OCR 自检失败")
    try:
        payload = json.loads(lines[0][len(_SELF_TEST_PREFIX):].decode("utf-8"))
        latency_ms = payload["latency_ms"]
        if (
            not isinstance(payload, dict)
            or payload.get("ready") is not True
            or isinstance(latency_ms, bool)
            or not isinstance(latency_ms, int)
            or latency_ms < 0
        ):
            raise ValueError("invalid self-test result")
    except (KeyError, TypeError, ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return OCRReadiness(False, "ocr_self_test_failed", "OCR 自检失败")
    return OCRReadiness(True, latency_ms=latency_ms)
