"""FastAPI application factory."""

from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Info, generate_latest
from sqlalchemy import create_engine

from atlas import __version__
from atlas.api.jobs import jobs_router
from atlas.api.sources import sources_router
from atlas.archive import open_archive
from atlas.health import (
    NOT_CONFIGURED,
    OK,
    check_archive,
    check_database,
    check_hindsight,
    check_litellm,
)
from atlas.hindsight import HindsightGateway
from atlas.jobs import JobQueue
from atlas.llm_routes import LiteLLMRoutes
from atlas.settings import Settings


def create_app(settings: Settings) -> FastAPI:
    app = FastAPI(title="Atlas Research")
    app.state.settings = settings
    engine = create_engine(settings.database_url, pool_pre_ping=True)
    archive = open_archive(settings)
    app.state.archive = archive
    hindsight = HindsightGateway.from_settings(settings)
    litellm = LiteLLMRoutes.from_settings(settings)
    registry = CollectorRegistry()
    Info("atlas_build", "Atlas build information", registry=registry).info({"version": __version__})

    @app.get("/health/live")
    def live() -> dict[str, str]:  # pyright: ignore[reportUnusedFunction]
        return {"status": "ok"}

    @app.get("/health/ready")
    def ready() -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        checks = {
            "database": check_database(engine),
            "archive": check_archive(archive),
            "hindsight": check_hindsight(hindsight),
            "litellm": check_litellm(litellm, settings.llm_aliases()),
        }
        is_ready = all(v in (OK, NOT_CONFIGURED) for v in checks.values())
        body: dict[str, Any] = {"status": "ready" if is_ready else "not_ready", "checks": checks}
        return JSONResponse(body, status_code=200 if is_ready else 503)

    @app.get("/metrics")
    def metrics() -> Response:  # pyright: ignore[reportUnusedFunction]
        return Response(generate_latest(registry), media_type=CONTENT_TYPE_LATEST)

    app.include_router(jobs_router(JobQueue(engine)))
    app.include_router(sources_router(engine, archive))

    # Mounted last so API routes take precedence over the static export.
    if settings.frontend_dir is not None:
        app.mount("/", StaticFiles(directory=settings.frontend_dir, html=True), name="frontend")

    return app
