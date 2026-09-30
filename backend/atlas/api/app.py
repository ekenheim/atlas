"""FastAPI application factory."""

from typing import Any

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Info, generate_latest

from atlas import __version__
from atlas.api.assertions import assertions_router
from atlas.api.candidates import candidates_router
from atlas.api.claims import claims_router
from atlas.api.common import invalid_request
from atlas.api.discovery import discovery_router
from atlas.api.dossier import dossier_router
from atlas.api.evaluations import evaluations_router
from atlas.api.financials import financials_router
from atlas.api.hypotheses import hypotheses_router
from atlas.api.identity import identity_router
from atlas.api.ingest_plans import ingest_plans_router
from atlas.api.investigations import investigations_router
from atlas.api.jobs import jobs_router
from atlas.api.memory import memory_router
from atlas.api.mental_models import mental_models_router
from atlas.api.proposed_updates import proposed_updates_router
from atlas.api.queue import queue_router
from atlas.api.relationships import relationships_router
from atlas.api.replay import replay_router
from atlas.api.research import research_router
from atlas.api.runs import runs_router
from atlas.api.scenarios import scenarios_router
from atlas.api.snapshots import snapshots_router
from atlas.api.sources import sources_router
from atlas.api.themes import themes_router
from atlas.api.tradingview import tradingview_router
from atlas.api.triage import triage_router
from atlas.archive import open_archive
from atlas.audit import Actor
from atlas.companies import load_universe
from atlas.db import create_engine
from atlas.health import (
    NOT_CONFIGURED,
    OK,
    check_archive,
    check_database,
    check_hindsight,
    check_litellm,
)
from atlas.hindsight import HindsightGateway
from atlas.jobs import Clock, JobQueue, Pacing, utc_now
from atlas.llm_routes import LiteLLMRoutes
from atlas.metrics import StateCollector, recall_latency
from atlas.settings import Settings


def create_app(settings: Settings, *, clock: Clock = utc_now) -> FastAPI:
    """The app. `clock` is the pacing clock (the pause and the backfill window)."""
    app = FastAPI(title="Atlas Research")
    # Request validation errors use the same error envelope as every other API error.
    app.add_exception_handler(RequestValidationError, invalid_request)
    app.state.settings = settings
    engine = create_engine(settings)
    archive = open_archive(settings)
    app.state.archive = archive
    hindsight = HindsightGateway.from_settings(settings)
    litellm = LiteLLMRoutes.from_settings(settings)
    queue = JobQueue(engine, pacing=Pacing.from_settings(settings), clock=clock)
    registry = CollectorRegistry()
    build_version = settings.version or __version__
    Info("atlas_build", "Atlas build information", registry=registry).info(
        {"version": build_version}
    )
    registry.register(StateCollector(engine, queue))

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

    app.include_router(jobs_router(queue))
    app.include_router(queue_router(queue))
    app.include_router(ingest_plans_router(engine))
    app.include_router(sources_router(engine, archive))
    app.include_router(financials_router(engine, settings.financial_metrics_config))
    app.include_router(assertions_router(engine, archive, Actor.from_settings(settings)))
    app.include_router(memory_router(engine, settings.hindsight_bank_id))
    app.include_router(
        triage_router(engine, archive, Actor.from_settings(settings), settings.hindsight_bank_id)
    )
    app.include_router(
        research_router(
            engine,
            archive,
            hindsight,
            Actor.from_settings(settings),
            settings.themes_config,
            recall_latency=recall_latency(registry),
        )
    )
    app.include_router(
        mental_models_router(engine, archive, hindsight, settings.hindsight_template_path)
    )
    app.include_router(runs_router(engine))
    app.include_router(claims_router(engine))
    app.include_router(discovery_router(engine))
    app.include_router(tradingview_router(engine))
    app.include_router(identity_router(engine, Actor.from_settings(settings)))
    app.include_router(relationships_router(engine, Actor.from_settings(settings)))
    app.include_router(
        investigations_router(engine, queue, Actor.from_settings(settings), settings)
    )
    app.include_router(
        candidates_router(
            engine,
            Actor.from_settings(settings),
            lambda: load_universe(settings.themes_config),
            ingest_lookback_days=settings.ingest_lookback_days,
        )
    )
    app.include_router(
        hypotheses_router(engine, queue, archive, Actor.from_settings(settings), settings)
    )
    app.include_router(
        themes_router(
            engine,
            archive,
            hindsight,
            settings.hindsight_template_path,
            lambda: load_universe(settings.themes_config),
        )
    )
    app.include_router(
        dossier_router(
            engine, settings.financial_metrics_config, lambda: load_universe(settings.themes_config)
        )
    )
    app.include_router(scenarios_router(engine, Actor.from_settings(settings)))
    app.include_router(snapshots_router(engine, archive))
    app.include_router(proposed_updates_router(engine, Actor.from_settings(settings)))

    app.include_router(evaluations_router(engine))
    app.include_router(replay_router(engine, queue, Actor.from_settings(settings), settings))

    # Mounted last so API routes take precedence over the static export.
    if settings.frontend_dir is not None:
        app.mount("/", StaticFiles(directory=settings.frontend_dir, html=True), name="frontend")

    return app
