"""Structured logging configuration for the Python LLM bridge.

Provides a JSON log formatter that matches Go slog's JSON output format,
and a setup_logging() function that configures the root logger.

Usage:
    from ulysses_ai.logging import setup_logging
    setup_logging(level="info", fmt="json")
    logger = logging.getLogger(__name__)
    logger.info("hello", extra={"key": "value"})
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone


class JSONFormatter(logging.Formatter):
    """Formats log records as JSON, matching Go slog's JSON output format.

    Output format:
        {"time":"2026-06-26T10:30:00.000+08:00","level":"INFO","msg":"message","key":"value"}
    """

    # Mapping from Python logging levels to Go slog level strings.
    LEVEL_MAP: dict[int, str] = {
        logging.DEBUG: "DEBUG",
        logging.INFO: "INFO",
        logging.WARNING: "WARN",
        logging.ERROR: "ERROR",
        logging.CRITICAL: "ERROR",
    }

    # Standard LogRecord fields that should not appear as extra keys.
    _STD_FIELDS: frozenset[str] = frozenset({
        "args", "asctime", "created", "exc_info", "exc_text",
        "filename", "funcName", "levelname", "levelno", "lineno",
        "message", "module", "msecs", "msg", "name", "pathname",
        "process", "processName", "relativeCreated", "stack_info",
        "taskName", "thread", "threadName",
    })

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, object] = {
            "time": self._format_time(record.created),
            "level": self.LEVEL_MAP.get(record.levelno, "INFO"),
            "msg": record.getMessage(),
        }

        # Merge extra fields from record.__dict__ (passed via extra={}).
        extras = {
            k: v for k, v in record.__dict__.items()
            if k not in self._STD_FIELDS and not k.startswith("_")
        }
        log_entry.update(extras)

        return json.dumps(log_entry, ensure_ascii=False, default=str, separators=(",", ":"))

    @staticmethod
    def _format_time(timestamp: float) -> str:
        """Format a Unix timestamp as RFC3339 with milliseconds and timezone offset.

        Matches Go's time.RFC3339Nano with millisecond precision:
            2006-01-02T15:04:05.000Z07:00
        """
        dt = datetime.fromtimestamp(timestamp, tz=timezone.utc).astimezone()
        ms = f"{dt.microsecond // 1000:03d}"
        tz = dt.strftime("%z")
        # Insert colon in timezone offset: +0800 → +08:00
        tz = f"{tz[:3]}:{tz[3:]}" if len(tz) == 5 else tz
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ms + tz


def setup_logging(level: str = "info", fmt: str = "json") -> None:
    """Configure the root logger for structured output to stderr.

    Args:
        level: One of "debug", "info", "warn", "error" (case-insensitive).
        fmt: "json" or "text".
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(_parse_level(level))

    # Remove existing handlers to avoid duplicates on reconfiguration.
    root_logger.handlers.clear()

    handler = logging.StreamHandler(stream=sys.stderr)
    if fmt == "json":
        handler.setFormatter(JSONFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))

    root_logger.addHandler(handler)


def _parse_level(level: str) -> int:
    """Convert a level string to a Python logging level constant."""
    mapping: dict[str, int] = {
        "debug": logging.DEBUG,
        "info": logging.INFO,
        "warn": logging.WARNING,
        "warning": logging.WARNING,
        "error": logging.ERROR,
    }
    return mapping.get(level.lower(), logging.INFO)
