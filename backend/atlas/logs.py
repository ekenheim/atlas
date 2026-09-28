"""Structured JSON logging to stderr."""

import logging
import sys

from pythonjsonlogger.json import JsonFormatter


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter("{asctime}{levelname}{name}{message}", style="{"))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
