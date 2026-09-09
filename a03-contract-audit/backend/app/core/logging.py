"""结构化日志：企业交付需要可观测性。审计日志单独走 audit_log 表（见 models）。"""
import logging
import sys

import structlog


class _EncodingSafeTextStream:
    """在不替换全局 stdout 的前提下兜底不可编码日志字符。"""

    def __init__(self, stream):
        self._stream = stream

    @property
    def encoding(self):
        return getattr(self._stream, "encoding", None)

    @property
    def errors(self) -> str:
        return "backslashreplace"

    def write(self, value: str):
        try:
            return self._stream.write(value)
        except UnicodeEncodeError:
            encoding = self.encoding or "utf-8"
            escaped = value.encode(encoding, errors="backslashreplace").decode(encoding)
            return self._stream.write(escaped)

    def flush(self):
        return self._stream.flush()

    def __getattr__(self, name: str):
        return getattr(self._stream, name)


def setup_logging(debug: bool = False) -> None:
    level = logging.DEBUG if debug else logging.INFO
    stream = sys.stdout
    reconfigure = getattr(stream, "reconfigure", None)
    if callable(reconfigure):
        try:
            reconfigure(encoding="utf-8", errors="backslashreplace")
        except (OSError, TypeError, ValueError):
            # 测试捕获流、IDE 控制台等可能暴露 reconfigure 但拒绝重配置。
            stream = _EncodingSafeTextStream(stream)
    else:
        stream = _EncodingSafeTextStream(stream)
    logging.basicConfig(format="%(message)s", stream=stream, level=level)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.dev.ConsoleRenderer() if debug else structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(file=stream),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str = "app"):
    return structlog.get_logger(name)
