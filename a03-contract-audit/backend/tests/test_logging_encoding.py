from app.core import logging as app_logging


class _ReconfigurableStream:
    def __init__(self):
        self.encoding = "gbk"
        self.errors = "strict"

    def reconfigure(self, *, encoding: str, errors: str) -> None:
        self.encoding = encoding
        self.errors = errors


class _PlainStream:
    encoding = "gbk"
    errors = "strict"

    def __init__(self):
        self.output = ""
        self.flush_count = 0

    def write(self, value: str) -> int:
        encoded = value.encode(self.encoding, errors=self.errors)
        rendered = encoded.decode(self.encoding)
        self.output += rendered
        return len(value)

    def flush(self) -> None:
        self.flush_count += 1


class _RejectingStream(_PlainStream):
    def reconfigure(self, **_kwargs) -> None:
        raise TypeError("stream does not accept encoding options")


def _isolate_logging(monkeypatch, stream):
    basic_config_calls = []
    structlog_configure_calls = []
    print_logger_factory_files = []
    monkeypatch.setattr(app_logging.sys, "stdout", stream)
    monkeypatch.setattr(
        app_logging.logging,
        "basicConfig",
        lambda **kwargs: basic_config_calls.append(kwargs),
    )
    monkeypatch.setattr(
        app_logging.structlog,
        "configure",
        lambda **kwargs: structlog_configure_calls.append(kwargs),
    )
    monkeypatch.setattr(
        app_logging.structlog,
        "PrintLoggerFactory",
        lambda file=None: print_logger_factory_files.append(file) or object(),
    )
    return basic_config_calls, structlog_configure_calls, print_logger_factory_files


def test_setup_logging_reconfigures_text_stream_with_safe_errors(monkeypatch):
    stream = _ReconfigurableStream()
    basic_config_calls, structlog_configure_calls, factory_files = _isolate_logging(
        monkeypatch, stream
    )

    app_logging.setup_logging()

    assert stream.encoding == "utf-8"
    assert stream.errors == "backslashreplace"
    assert basic_config_calls[0]["stream"] is stream
    assert factory_files == [stream]
    assert len(structlog_configure_calls) == 1


def test_setup_logging_keeps_stream_without_reconfigure(monkeypatch):
    stream = _PlainStream()
    basic_config_calls, structlog_configure_calls, factory_files = _isolate_logging(
        monkeypatch, stream
    )

    app_logging.setup_logging()

    assert stream.encoding == "gbk"
    assert stream.errors == "strict"
    assert basic_config_calls[0]["stream"] is not stream
    assert factory_files == [basic_config_calls[0]["stream"]]
    assert len(structlog_configure_calls) == 1


def test_setup_logging_keeps_stream_when_reconfigure_rejects_options(monkeypatch):
    stream = _RejectingStream()
    basic_config_calls, structlog_configure_calls, factory_files = _isolate_logging(
        monkeypatch, stream
    )

    app_logging.setup_logging()

    assert stream.encoding == "gbk"
    assert stream.errors == "strict"
    assert basic_config_calls[0]["stream"] is not stream
    assert factory_files == [basic_config_calls[0]["stream"]]
    assert len(structlog_configure_calls) == 1


def test_safe_stream_escapes_unencodable_characters_without_replacing_stdout(monkeypatch):
    stream = _PlainStream()
    basic_config_calls, _, factory_files = _isolate_logging(monkeypatch, stream)

    app_logging.setup_logging()
    safe_stream = basic_config_calls[0]["stream"]
    safe_stream.write("兼容部首: \u2f83")
    safe_stream.flush()

    assert app_logging.sys.stdout is stream
    assert stream.output == "兼容部首: \\u2f83"
    assert stream.flush_count == 1
    assert factory_files == [safe_stream]
