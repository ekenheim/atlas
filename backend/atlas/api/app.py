"""FastAPI application factory."""

from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import create_engine

from atlas.health import NOT_CONFIGURED, OK, check_archive, check_database
from atlas.settings import Settings


def create_app(settings: Settings) -> FastAPI:
    app = FastAPI(title="Atlas Research")
    app.state.settings = settings
    engine = create_engine(settings.database_url, pool_pre_ping=True)

    @app.get("/health/live")
    def live() -> dict[str, str]:  # pyright: ignore[reportUnusedFunction]
        return {"status": "ok"}

    @app.get("/health/ready")
    def ready() -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        checks = {
            "database": check_database(engine),
            "archive": check_archive(settings.archive_root),
            "hindsight": NOT_CONFIGURED,
            "litellm": NOT_CONFIGURED,
        }
        is_ready = all(v in (OK, NOT_CONFIGURED) for v in checks.values())
        body: dict[str, Any] = {"status": "ready" if is_ready else "not_ready", "checks": checks}
        return JSONResponse(body, status_code=200 if is_ready else 503)

    return app
