"""RapidOCR 子进程入口：通过标准输入/输出传递版本化协议。"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import sys

from app.services.parser.ocr import (
    OCRError,
    RapidOCREngine,
    _WORKER_RESULT_PREFIX,
    _ocr_pdf_bytes_in_process,
)


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
    parser.add_argument("--max-pages", type=int, required=True)
    parser.add_argument("--max-page-pixels", type=int, required=True)
    parser.add_argument("--dpi", type=int, required=True)
    parser.add_argument("--timeout-seconds", type=float, required=True)
    parser.add_argument("--min-confidence", type=float, required=True)
    parser.add_argument("--page-indices")
    return parser


def _write_payload(payload: dict[str, object]) -> None:
    encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    sys.stdout.buffer.write(_WORKER_RESULT_PREFIX + encoded + b"\n")
    sys.stdout.buffer.flush()


def main() -> int:
    args = _parser().parse_args()
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
