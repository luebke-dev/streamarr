"""Centralized logging configuration for the Streamarr backend.

Supports two output formats controlled by LOG_FORMAT env var:
- "text" (default): Human-readable colored output for development
- "json": Structured JSON lines for production / log aggregation

Log level is controlled by LOG_LEVEL env var (default: INFO).
"""

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)


_RESERVED = {
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
    "created", "msecs", "relativeCreated", "thread", "threadName",
    "processName", "process", "message", "asctime", "taskName",
}

# Keys whose value is replaced with ``***`` when they appear in ``extra={...}``
# so a careless caller (``logger.info("login", extra={"password": pw})``) can't
# bleed secrets into the log stream. Match is case-insensitive and substring-
# based (``refresh_token`` and ``access_token_secret`` both trip ``token``).
_SENSITIVE_KEY_FRAGMENTS = (
    "password",
    "secret",
    "token",
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "session",
    "credential",
    "private_key",
    "jwt",
)


def _is_sensitive_key(key: str) -> bool:
    k = key.lower()
    return any(fragment in k for fragment in _SENSITIVE_KEY_FRAGMENTS)


class JSONFormatter(logging.Formatter):
    """Outputs log records as single-line JSON objects.

    Any keyword arguments passed via ``logger.info("msg", extra={...})`` are
    merged into the output so call sites can attach request_id, user_id,
    media_guid etc. without a second log line.
    """

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "line": record.lineno,
        }
        request_id = request_id_var.get()
        if request_id:
            entry["request_id"] = request_id
        for key, value in record.__dict__.items():
            if key in _RESERVED or key.startswith("_"):
                continue
            entry[key] = "***" if _is_sensitive_key(key) else value
        if record.exc_info and record.exc_info[0] is not None:
            entry["exception"] = self.formatException(record.exc_info)
        if record.stack_info:
            entry["stack"] = record.stack_info
        return json.dumps(entry, default=str)


class TextFormatter(logging.Formatter):
    """Compact, human-readable log format for development."""

    LEVEL_COLORS = {
        "DEBUG": "\033[36m",     # cyan
        "INFO": "\033[32m",      # green
        "WARNING": "\033[33m",   # yellow
        "ERROR": "\033[31m",     # red
        "CRITICAL": "\033[1;31m",  # bold red
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        color = self.LEVEL_COLORS.get(record.levelname, "")
        level = f"{color}{record.levelname:<8}{self.RESET}"
        msg = record.getMessage()
        base = f"{level} {record.name}: {msg}"
        if record.exc_info and record.exc_info[0] is not None:
            base += "\n" + self.formatException(record.exc_info)
        return base


def setup_logging(level: str = "INFO", fmt: str = "text") -> None:
    """Configure the root logger and uvicorn loggers.

    Should be called once at application startup before any other logging.
    """
    log_level = getattr(logging, level.upper(), logging.INFO)

    # Choose formatter
    if fmt.lower() == "json":
        formatter = JSONFormatter()
    else:
        formatter = TextFormatter()

    # Configure root handler
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(log_level)

    # Align uvicorn loggers so all output goes through the same formatter
    for name in ("uvicorn", "uvicorn.access", "uvicorn.error"):
        uv_logger = logging.getLogger(name)
        uv_logger.handlers.clear()
        uv_logger.addHandler(handler)
        uv_logger.propagate = False

    # Quieten noisy third-party loggers
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("aiodocker").setLevel(logging.WARNING)
    logging.getLogger("aiosqlite").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(
        logging.WARNING if log_level > logging.DEBUG else logging.INFO
    )
