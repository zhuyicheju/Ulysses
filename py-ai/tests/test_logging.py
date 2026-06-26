"""Tests for ulysses_ai.logging — JSON formatter and setup_logging."""

from __future__ import annotations

import io
import json
import logging
import re
import sys

import pytest

from ulysses_ai.logging import JSONFormatter, setup_logging, _parse_level


# ---------------------------------------------------------------------------
# JSONFormatter
# ---------------------------------------------------------------------------

class TestJSONFormatter:
    """Tests for the JSONFormatter that matches Go slog output."""

    def test_output_contains_required_keys(self):
        """JSON output must have time, level, msg keys."""
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="hello world", args=(), exc_info=None,
        )
        output = formatter.format(record)
        entry = json.loads(output)

        assert "time" in entry
        assert "level" in entry
        assert "msg" in entry

    def test_level_mapping(self):
        """Python levels must map to slog level strings."""
        formatter = JSONFormatter()
        cases = [
            (logging.DEBUG, "DEBUG"),
            (logging.INFO, "INFO"),
            (logging.WARNING, "WARN"),
            (logging.ERROR, "ERROR"),
            (logging.CRITICAL, "ERROR"),
        ]
        for levelno, expected in cases:
            record = logging.LogRecord(
                name="test", level=levelno, pathname="", lineno=0,
                msg="test", args=(), exc_info=None,
            )
            entry = json.loads(formatter.format(record))
            assert entry["level"] == expected, f"level {levelno} -> {entry['level']}, want {expected}"

    def test_message_field(self):
        """The msg field should contain the formatted message."""
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="user %s logged in", args=("alice",), exc_info=None,
        )
        entry = json.loads(formatter.format(record))
        assert entry["msg"] == "user alice logged in"

    def test_time_format_rfc3339(self):
        """Time must be RFC3339 with milliseconds and timezone offset."""
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="test", args=(), exc_info=None,
        )
        entry = json.loads(formatter.format(record))
        time_str = entry["time"]

        # Must match: YYYY-MM-DDTHH:MM:SS.mmm±HH:MM
        pattern = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}[+-]\d{2}:\d{2}$"
        assert re.match(pattern, time_str), f"time format mismatch: {time_str}"

    def test_extra_fields_appear_in_output(self):
        """Extra fields passed via extra={} must appear in JSON."""
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="request", args=(), exc_info=None,
        )
        # Simulate extra fields by setting them on the record.
        record.component = "server"
        record.request_id = "abc-123"

        entry = json.loads(formatter.format(record))
        assert entry.get("component") == "server"
        assert entry.get("request_id") == "abc-123"

    def test_standard_logrecord_fields_are_excluded(self):
        """Standard LogRecord fields must not appear as extra keys."""
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="test.py", lineno=42,
            msg="test", args=(), exc_info=None,
        )
        entry = json.loads(formatter.format(record))

        # These are standard LogRecord fields and should NOT be in the output.
        excluded = {"name", "levelno", "pathname", "lineno", "funcName",
                     "module", "filename", "process", "processName",
                     "thread", "threadName"}
        for key in excluded:
            assert key not in entry, f"standard field '{key}' leaked into output"

    def test_json_is_valid_utf8(self):
        """Output must be valid UTF-8 with non-ASCII preserved."""
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="你好世界", args=(), exc_info=None,
        )
        output = formatter.format(record)
        entry = json.loads(output)
        assert entry["msg"] == "你好世界"


# ---------------------------------------------------------------------------
# _parse_level
# ---------------------------------------------------------------------------

class TestParseLevel:
    """Tests for the internal level parser."""

    def test_known_levels(self):
        assert _parse_level("debug") == logging.DEBUG
        assert _parse_level("info") == logging.INFO
        assert _parse_level("warn") == logging.WARNING
        assert _parse_level("warning") == logging.WARNING
        assert _parse_level("error") == logging.ERROR

    def test_case_insensitive(self):
        assert _parse_level("DEBUG") == logging.DEBUG
        assert _parse_level("Info") == logging.INFO
        assert _parse_level("WARN") == logging.WARNING

    def test_unknown_defaults_to_info(self):
        assert _parse_level("bogus") == logging.INFO
        assert _parse_level("") == logging.INFO


# ---------------------------------------------------------------------------
# setup_logging
# ---------------------------------------------------------------------------

class TestSetupLogging:
    """Tests for the setup_logging function."""

    def setup_method(self):
        """Reset root logger before each test."""
        root = logging.getLogger()
        root.handlers.clear()
        root.setLevel(logging.WARNING)  # default

    def teardown_method(self):
        """Clean up root logger after each test."""
        root = logging.getLogger()
        root.handlers.clear()

    def test_sets_level_on_root_logger(self):
        setup_logging(level="debug")
        assert logging.getLogger().level == logging.DEBUG

    def test_default_level_is_info(self):
        setup_logging()
        assert logging.getLogger().level == logging.INFO

    def test_adds_stream_handler(self):
        setup_logging()
        handlers = logging.getLogger().handlers
        assert len(handlers) == 1
        assert isinstance(handlers[0], logging.StreamHandler)

    def test_stream_handler_writes_to_stderr(self):
        setup_logging()
        handler = logging.getLogger().handlers[0]
        assert handler.stream is sys.stderr

    def test_json_format_uses_json_formatter(self):
        setup_logging(fmt="json")
        handler = logging.getLogger().handlers[0]
        assert isinstance(handler.formatter, JSONFormatter)

    def test_text_format_uses_standard_formatter(self):
        setup_logging(fmt="text")
        handler = logging.getLogger().handlers[0]
        assert isinstance(handler.formatter, logging.Formatter)
        assert not isinstance(handler.formatter, JSONFormatter)

    def test_clears_existing_handlers(self):
        # Add a dummy handler first.
        root = logging.getLogger()
        handler = logging.StreamHandler(io.StringIO())
        root.addHandler(handler)

        setup_logging()
        # The old handler should have been removed.
        assert handler not in root.handlers
        # At least one new handler should be present.
        assert len(root.handlers) >= 1

    def test_logger_produces_json_to_stderr(self, capsys):
        """Integration: a logger configured by setup_logging writes JSON to stderr."""
        setup_logging(level="info", fmt="json")
        logger = logging.getLogger("test_integration")
        logger.info("integration test", extra={"key": "value"})

        captured = capsys.readouterr()
        # Output goes to stderr.
        assert captured.err != ""
        entry = json.loads(captured.err.strip())
        assert entry["msg"] == "integration test"
        assert entry["key"] == "value"
        assert entry["level"] == "INFO"
