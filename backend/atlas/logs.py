"""Structured JSON logging to stderr, with secrets redacted from every record."""

import logging
import re
import sys

from pythonjsonlogger.json import JsonFormatter

REDACTED = "[REDACTED]"

# Applied to the fully formatted record (message, extras and tracebacks alike).
_SECRET_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # Credentials embedded in URLs: scheme://user:password@host
    (re.compile(r"(://[^:/@\s\"]+:)[^@\s\"]+(@)"), rf"\1{REDACTED}\2"),
    # HTTP bearer tokens
    (re.compile(r"(Bearer\s+)[^\s\"]+", re.IGNORECASE), rf"\1{REDACTED}"),
    # LiteLLM / OpenAI-style API keys
    (re.compile(r"\bsk-[A-Za-z0-9_-]{8,}"), REDACTED),
    # key=value or key: value where the key names a secret
    (
        re.compile(
            r"((?:password|passwd|secret|token|api[_-]?key|access[_-]?key)[A-Za-z_]*\s*[=:]\s*)"
            r"[^\s\"',]+",
            re.IGNORECASE,
        ),
        rf"\1{REDACTED}",
    ),
]


def redact(text: str) -> str:
    for pattern, replacement in _SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


class RedactingJsonFormatter(JsonFormatter):
    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(RedactingJsonFormatter("{asctime}{levelname}{name}{message}", style="{"))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
