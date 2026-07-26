"""离线 OCR 适配层：限制资源消耗，并保留识别质量信息。"""
from __future__ import annotations

from dataclasses import dataclass
import json
import math
import subprocess
import sys
import time
from typing import Callable, Protocol, runtime_checkable


class OCRError(RuntimeError):
    """OCR 处理失败。"""


class OCRUnavailable(OCRError):
    """OCR 运行时或模型不可用。"""


class OCRLimitExceeded(OCRError):
    """输入超过 OCR 资源限制。"""


class OCRTimeout(OCRError):
    """OCR 总处理时间超过限制。"""


@dataclass(frozen=True)
class OCRResult:
    text: str
    page_count: int
    mean_confidence: float
    page_texts: tuple[str, ...] = ()
    requires_review: bool = False


_WORKER_RESULT_PREFIX = b"A03_OCR_RESULT_V1="
_ERROR_TYPES: dict[str, type[OCRError]] = {
    "OCRError": OCRError,
    "OCRUnavailable": OCRUnavailable,
    "OCRLimitExceeded": OCRLimitExceeded,
    "OCRTimeout": OCRTimeout,
}


@runtime_checkable
class OCREngine(Protocol):
    def recognize(self, image: bytes) -> tuple[str, float]: ...


EngineLike = OCREngine | Callable[[bytes], tuple[str, float]]


class RapidOCREngine:
    """RapidOCR 3.x 懒加载适配器，避免应用启动时强制加载模型。"""

    def __init__(self) -> None:
        self._engine: object | None = None

    def _load(self) -> object:
        if self._engine is not None:
            return self._engine
        try:
            from rapidocr import RapidOCR
        except ImportError as exc:
            raise OCRUnavailable(
                "RapidOCR 未安装，扫描件无法解析；请安装交付清单中固定版本的 OCR 依赖"
            ) from exc
        try:
            self._engine = RapidOCR()
        except Exception as exc:
            raise OCRUnavailable(f"RapidOCR 模型加载失败: {exc}") from exc
        return self._engine

    def recognize(self, image: bytes) -> tuple[str, float]:
        try:
            output = self._load()(image)  # type: ignore[operator]
        except OCRUnavailable:
            raise
        except Exception as exc:
            raise OCRError(f"RapidOCR 识别失败: {exc}") from exc

        texts = list(getattr(output, "txts", None) or ())
        scores = [float(value) for value in (getattr(output, "scores", None) or ())]
        if not texts and isinstance(output, tuple) and output:
            lines = output[0] or ()
            texts = [str(line[1]) for line in lines if len(line) >= 3]
            scores = [float(line[2]) for line in lines if len(line) >= 3]
        confidence = sum(scores) / len(scores) if scores else 0.0
        return "\n".join(texts).strip(), confidence


def _recognize(engine: EngineLike, image: bytes) -> tuple[str, float]:
    if isinstance(engine, OCREngine):
        return engine.recognize(image)
    return engine(image)


def _communicate_with_timeout(
    process: subprocess.Popen[bytes], data: bytes, *, timeout_seconds: float
) -> tuple[bytes, bytes]:
    try:
        return process.communicate(input=data, timeout=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        process.terminate()
        try:
            process.communicate(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
        raise OCRTimeout(f"OCR 处理超过 {timeout_seconds:g} 秒") from exc


def _parse_worker_result(stdout: bytes) -> OCRResult:
    line = next(
        (
            line
            for line in reversed(stdout.splitlines())
            if line.startswith(_WORKER_RESULT_PREFIX)
        ),
        None,
    )
    if line is None:
        raise OCRError("OCR 子进程响应协议无效")
    try:
        payload = json.loads(line[len(_WORKER_RESULT_PREFIX):].decode("utf-8"))
        if not isinstance(payload, dict):
            raise TypeError("响应不是对象")
        if not payload.get("ok"):
            error_type = _ERROR_TYPES.get(str(payload.get("error_type")), OCRError)
            raise error_type(str(payload.get("message") or "OCR 子进程失败"))
        result = payload["result"]
        return OCRResult(
            text=str(result["text"]),
            page_count=int(result["page_count"]),
            mean_confidence=float(result["mean_confidence"]),
            page_texts=tuple(str(value) for value in result.get("page_texts", [])),
            requires_review=bool(result["requires_review"]),
        )
    except OCRError:
        raise
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise OCRError("OCR 子进程响应协议无效") from exc


def _ocr_pdf_bytes_in_process(
    data: bytes,
    *,
    engine: EngineLike,
    page_indices: tuple[int, ...] | list[int] | None = None,
    max_pages: int = 100,
    max_page_pixels: int = 16_000_000,
    dpi: int = 180,
    timeout_seconds: float = 120.0,
    min_confidence: float = 0.75,
) -> OCRResult:
    """在当前进程渲染并识别 PDF 页面；页索引从 0 开始。"""
    if max_pages < 1 or max_page_pixels < 1 or dpi < 36 or timeout_seconds <= 0:
        raise ValueError("OCR 资源限制参数无效")

    try:
        import fitz

        document = fitz.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise OCRError(f"PDF 无法打开: {exc}") from exc

    started_at = time.monotonic()
    try:
        selected = tuple(range(document.page_count)) if page_indices is None else tuple(page_indices)
        if len(selected) > max_pages:
            raise OCRLimitExceeded(f"OCR 页数 {len(selected)} 超过上限 {max_pages}")
        if len(set(selected)) != len(selected) or any(i < 0 or i >= document.page_count for i in selected):
            raise OCRLimitExceeded("OCR 页索引无效或重复")

        page_texts: list[str] = []
        confidences: list[float] = []
        scale = dpi / 72.0

        for index in selected:
            if time.monotonic() - started_at > timeout_seconds:
                raise OCRTimeout(f"OCR 处理超过 {timeout_seconds:g} 秒")
            page = document.load_page(index)
            pixel_count = math.ceil(page.rect.width * scale) * math.ceil(page.rect.height * scale)
            if pixel_count > max_page_pixels:
                raise OCRLimitExceeded(
                    f"第 {index + 1} 页像素 {pixel_count} 超过上限 {max_page_pixels}"
                )
            pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
            text, confidence = _recognize(engine, pixmap.tobytes("png"))
            page_texts.append(text.strip())
            confidences.append(max(0.0, min(1.0, float(confidence))))
            if time.monotonic() - started_at > timeout_seconds:
                raise OCRTimeout(f"OCR 处理超过 {timeout_seconds:g} 秒")
    finally:
        document.close()

    combined = "\n".join(text for text in page_texts if text).strip()
    mean_confidence = sum(confidences) / len(confidences) if confidences else 0.0
    return OCRResult(
        text=combined,
        page_count=len(page_texts),
        mean_confidence=mean_confidence,
        page_texts=tuple(page_texts),
        requires_review=not combined or mean_confidence < min_confidence,
    )


def ocr_pdf_bytes(
    data: bytes,
    *,
    engine: EngineLike | None = None,
    page_indices: tuple[int, ...] | list[int] | None = None,
    max_pages: int = 100,
    max_page_pixels: int = 16_000_000,
    dpi: int = 180,
    timeout_seconds: float = 120.0,
    min_confidence: float = 0.75,
) -> OCRResult:
    """识别 PDF；生产引擎在可强制终止的子进程中运行。"""
    if max_pages < 1 or max_page_pixels < 1 or dpi < 36 or timeout_seconds <= 0:
        raise ValueError("OCR 资源限制参数无效")

    if engine is not None:
        return _ocr_pdf_bytes_in_process(
            data,
            engine=engine,
            page_indices=page_indices,
            max_pages=max_pages,
            max_page_pixels=max_page_pixels,
            dpi=dpi,
            timeout_seconds=timeout_seconds,
            min_confidence=min_confidence,
        )

    command = [
        sys.executable,
        "-m",
        "app.services.parser.ocr_worker",
        "--max-pages",
        str(max_pages),
        "--max-page-pixels",
        str(max_page_pixels),
        "--dpi",
        str(dpi),
        "--timeout-seconds",
        str(timeout_seconds),
        "--min-confidence",
        str(min_confidence),
    ]
    if page_indices is not None:
        command.extend(["--page-indices", ",".join(str(value) for value in page_indices)])
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as exc:
        raise OCRUnavailable(f"OCR 子进程启动失败: {exc}") from exc

    stdout, stderr = _communicate_with_timeout(
        process,
        data,
        timeout_seconds=timeout_seconds,
    )
    if process.returncode not in (0, None) and _WORKER_RESULT_PREFIX not in stdout:
        detail = stderr.decode("utf-8", errors="replace")[-1000:]
        raise OCRUnavailable(
            f"OCR 子进程启动或执行失败: {detail or process.returncode}"
        )
    return _parse_worker_result(stdout)
