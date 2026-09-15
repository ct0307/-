"""RapidOCR 子进程入口：通过标准输入/输出传递版本化协议。"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import asdict
import json
import os
import socket
import sys
import time

from app.services.parser.ocr import (
    OCRError,
    RapidOCREngine,
    _WORKER_RESULT_PREFIX,
    _ocr_pdf_bytes_in_process,
    block_rapidocr_downloads as _block_rapidocr_downloads,
    create_offline_ocr_engine,
    offline_rapidocr_params as _offline_rapidocr_params,
)


_SELF_TEST_PREFIX = b"A03_OCR_SELF_TEST_V1="


def _parse_page_indices(value: str | None) -> tuple[int, ...] | None:
    if value is None:
        return None
    if not value:
        return ()
    try:
        return tuple(int(item) for item in value.split(","))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("页索引必须为逗号分隔整数") from exc


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--max-pages", type=int)
    parser.add_argument("--max-page-pixels", type=int)
    parser.add_argument("--dpi", type=int)
    parser.add_argument("--timeout-seconds", type=float)
    parser.add_argument("--min-confidence", type=float)
    parser.add_argument("--page-indices")
    return parser


def _write_payload(payload: dict[str, object]) -> None:
    encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    sys.stdout.buffer.write(_WORKER_RESULT_PREFIX + encoded + b"\n")
    sys.stdout.buffer.flush()


def _write_self_test_payload(payload: dict[str, object]) -> None:
    encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    sys.stdout.buffer.write(_SELF_TEST_PREFIX + encoded + b"\n")
    sys.stdout.buffer.flush()


def _self_test_image() -> bytes:
    import fitz

    document = fitz.open()
    try:
        page = document.new_page(width=600, height=130)
        page.insert_text((60, 80), "CONTRACT 10000", fontsize=36, fontname="helv")
        pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
        return pixmap.tobytes("png")
    finally:
        document.close()


def _create_self_test_engine() -> RapidOCREngine:
    return create_offline_ocr_engine()


@contextmanager
def _block_network_when_requested():
    """测试模式下封锁 socket 连接，并记录任何联网尝试。"""
    if os.environ.get("A03_OCR_SELF_TEST_BLOCK_NETWORK") != "1":
        yield None
        return

    attempts = 0
    original_connect = socket.socket.connect
    original_create_connection = socket.create_connection

    def blocked_connect(_socket, *_args, **_kwargs):
        nonlocal attempts
        attempts += 1
        raise OSError("OCR 自检测试禁止网络连接")

    def blocked_create_connection(*_args, **_kwargs):
        nonlocal attempts
        attempts += 1
        raise OSError("OCR 自检测试禁止网络连接")

    socket.socket.connect = blocked_connect
    socket.create_connection = blocked_create_connection
    try:
        yield lambda: attempts
    finally:
        socket.socket.connect = original_connect
        socket.create_connection = original_create_connection


def _run_self_test(engine: RapidOCREngine | None = None) -> dict[str, object]:
    started = time.monotonic()
    text, confidence = (engine or _create_self_test_engine()).recognize(_self_test_image())
    if "CONTRACT" not in text.upper() or confidence <= 0:
        raise RuntimeError("OCR 自检识别结果不符合预期")
    return {"ready": True, "latency_ms": round((time.monotonic() - started) * 1000)}


def _validate_ocr_arguments(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    required = ("max_pages", "max_page_pixels", "dpi", "timeout_seconds", "min_confidence")
    if any(getattr(args, name) is None for name in required):
        parser.error("非自检模式必须提供全部 OCR 参数")


def main() -> int:
    parser = _parser()
    args = parser.parse_args()
    if args.self_test:
        try:
            with _block_network_when_requested() as network_attempts:
                payload = _run_self_test()
                if network_attempts is not None:
                    payload["network_attempts"] = network_attempts()
            _write_self_test_payload(payload)
            return 0
        except Exception:
            _write_self_test_payload({"ready": False})
            return 2

    _validate_ocr_arguments(args, parser)
    data = sys.stdin.buffer.read()
    try:
        result = _ocr_pdf_bytes_in_process(
            data,
            engine=create_offline_ocr_engine(),
            page_indices=_parse_page_indices(args.page_indices),
            max_pages=args.max_pages,
            max_page_pixels=args.max_page_pixels,
            dpi=args.dpi,
            timeout_seconds=args.timeout_seconds,
            min_confidence=args.min_confidence,
        )
    except OCRError as exc:
        _write_payload(
            {
                "ok": False,
                "error_type": type(exc).__name__,
                "message": str(exc),
            }
        )
        return 2
    except Exception:
        _write_payload(
            {
                "ok": False,
                "error_type": "OCRError",
                "message": "OCR 子进程发生未预期错误",
            }
        )
        return 2

    _write_payload({"ok": True, "result": asdict(result)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
