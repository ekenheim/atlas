"""The `tradingview_catalog` and `tradingview_transcripts` job handlers (not pausable: a
TradingView outage says nothing about Hindsight or LiteLLM; both are `tradingview` budget
kinds). With ATLAS_TRADINGVIEW_ENABLED off they fail at once, calling nothing."""

from atlas.db import create_engine
from atlas.jobs.handlers import HandlerRegistry
from atlas.jobs.pacing import Clock
from atlas.jobs.queue import Artifacts, Job
from atlas.settings import Settings
from atlas.tradingview.model import CATALOG_KIND, TRANSCRIPTS_KIND
from atlas.tradingview.service import require_enabled, run_catalog, run_transcripts


def register_tradingview_handlers(
    registry: HandlerRegistry, settings: Settings, clock: Clock
) -> None:
    def catalog(job: Job) -> Artifacts:
        require_enabled(settings)
        engine = create_engine(settings)
        try:
            return run_catalog(settings, engine, job, clock())
        finally:
            engine.dispose()

    def transcripts(job: Job) -> Artifacts:
        require_enabled(settings)
        engine = create_engine(settings)
        try:
            return run_transcripts(settings, engine, job, clock())
        finally:
            engine.dispose()

    registry.register(CATALOG_KIND, catalog)
    registry.register(TRANSCRIPTS_KIND, transcripts)
