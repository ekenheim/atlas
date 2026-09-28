"""Readiness checks: the truth about whether the whole flow can work."""

from sqlalchemy import Engine, text

from atlas.archive import Archive

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


def check_archive(archive: Archive) -> str:
    """The configured backend: a writable root directory, or a reachable S3 bucket."""
    try:
        return OK if archive.is_ready() else DOWN
    except Exception:
        return DOWN
