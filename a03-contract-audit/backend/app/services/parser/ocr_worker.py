"""RapidOCR 子进程入口：通过标准输入/输出传递版本化协议。"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from io import BytesIO
import json
import sys
import time

from app.services.parser.ocr import (
    OCRError,
    RapidOCREngine,
    _WORKER_RESULT_PREFIX,
    _ocr_pdf_bytes_in_process,
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


def _self_test_font():
    from PIL import ImageFont

    candidates = (
        "DejaVuSans.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    )
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, 64)
        except OSError:
            continue
    raise RuntimeError("OCR 自检未找到可用字体")


def _self_test_image() -> bytes:
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (1200, 260), "white")
    ImageDraw.Draw(image).text((60, 80), "CONTRACT 10000", fill="black", font=_self_test_font())
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _run_self_test(engine: RapidOCREngine | None = None) -> dict[str, object]:
    started = time.monotonic()
    text, confidence = (engine or RapidOCREngine()).recognize(_self_test_image())
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
            _write_self_test_payload(_run_self_test())
            return 0
        except Exception:
            _write_self_test_payload({"ready": False})
            return 2

    _validate_ocr_arguments(args, parser)
    data = sys.stdin.buffer.read()
    try:
        result = _ocr_pdf_bytes_in_process(
            data,
            engine=RapidOCREngine(),
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
