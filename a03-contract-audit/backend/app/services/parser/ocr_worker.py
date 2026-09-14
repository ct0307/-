"""RapidOCR 子进程入口：通过标准输入/输出传递版本化协议。"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
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


def _model_sha256(path: Path) -> str:
    with path.open("rb") as model_file:
        return hashlib.file_digest(model_file, "sha256").hexdigest()


def _offline_rapidocr_params(*, model_dir: Path | None = None) -> dict[str, object]:
    """使用 RapidOCR 3.9.2 清单校验包内 ONNX 模型，拒绝缺失或损坏模型。"""
    import rapidocr
    from rapidocr.inference_engine.base import FileInfo, InferSession
    from rapidocr.utils.typings import EngineType, ModelType, OCRVersion, TaskType

    model_dir = model_dir or Path(rapidocr.__file__).resolve().parent / "models"
    specs = (
        ("Det.model_path", FileInfo(EngineType.ONNXRUNTIME, OCRVersion.PPOCRV6, TaskType.DET, "ch", ModelType.SMALL)),
        ("Cls.model_path", FileInfo(EngineType.ONNXRUNTIME, OCRVersion.PPOCRV4, TaskType.CLS, "ch", ModelType.MOBILE)),
        ("Rec.model_path", FileInfo(EngineType.ONNXRUNTIME, OCRVersion.PPOCRV6, TaskType.REC, "ch", ModelType.SMALL)),
    )
    params: dict[str, object] = {}
    for parameter, file_info in specs:
        metadata = InferSession.get_model_url(file_info)
        model_path = model_dir / Path(metadata["model_dir"]).name
        if not model_path.is_file() or _model_sha256(model_path) != metadata["SHA256"]:
            raise RuntimeError("OCR 自检本地模型不可用")
        params[parameter] = str(model_path)
    return params


@contextmanager
def _block_rapidocr_downloads():
    """仅在自检初始化期间拦截 RapidOCR 3.9.2 的实际 HTTP 下载入口。"""
    from rapidocr.utils.download_file import DownloadFile

    original = DownloadFile.__dict__["_make_http_request"]

    def blocked_download(_cls, *_args, **_kwargs):
        raise RuntimeError("OCR 自检禁止联网下载模型")

    DownloadFile._make_http_request = classmethod(blocked_download)
    try:
        yield
    finally:
        DownloadFile._make_http_request = original


def _create_self_test_engine() -> RapidOCREngine:
    params = _offline_rapidocr_params()
    engine = RapidOCREngine(params=params)
    with _block_rapidocr_downloads():
        engine._load()
    return engine


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
