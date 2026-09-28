"""Readiness checks: the truth about whether the whole flow can work."""

from collections.abc import Sequence

from sqlalchemy import Engine, text

from atlas.archive import Archive
from atlas.hindsight import HindsightGateway
from atlas.llm_routes import LiteLLMRoutes

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


def check_hindsight(gateway: HindsightGateway | None) -> str:
    """The server answers `/health` as healthy (so its database is reachable)."""
    if gateway is None:
        return NOT_CONFIGURED
    try:
        return OK if gateway.server_health().is_healthy else DOWN
    except Exception:
        return DOWN


def check_litellm(routes: LiteLLMRoutes | None, aliases: Sequence[str]) -> str:
    """LiteLLM accepts Atlas's key and routes every alias Atlas uses (no model is called)."""
    if routes is None:
        return NOT_CONFIGURED
    try:
        routes.routes(aliases)
    except Exception:
        return DOWN
    return OK
