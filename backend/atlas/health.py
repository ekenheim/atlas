"""Readiness checks: the truth about whether the whole flow can work."""

import os
from pathlib import Path

from sqlalchemy import Engine, text

OK = "ok"
DOWN = "down"
NOT_CONFIGURED = "not_configured"


def check_database(engine: Engine) -> str:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception:
        return DOWN
    return OK


def check_archive(root: Path) -> str:
    return OK if root.is_dir() and os.access(root, os.W_OK) else DOWN
