"""The TradingView job handlers: `tradingview_catalog`, `tradingview_transcripts`,
`tradingview_calendar` and `tradingview_prices` (not pausable: a TradingView outage says
nothing about Hindsight or LiteLLM; all are `tradingview` budget kinds). With
ATLAS_TRADINGVIEW_ENABLED off they fail at once, calling nothing."""

from collections.abc import Callable
from datetime import datetime

from sqlalchemy import Engine

from atlas.db import create_engine
from atlas.jobs.handlers import HandlerRegistry
from atlas.jobs.pacing import Clock
from atlas.jobs.queue import Artifacts, Job
from atlas.settings import Settings
from atlas.tradingview.model import CALENDAR_KIND, CATALOG_KIND, PRICES_KIND, TRANSCRIPTS_KIND
from atlas.tradingview.prices import run_prices
from atlas.tradingview.schedule import run_calendar
from atlas.tradingview.service import require_enabled, run_catalog, run_transcripts

type Run = Callable[[Settings, Engine, Job, datetime], Artifacts]


def register_tradingview_handlers(
    registry: HandlerRegistry, settings: Settings, clock: Clock
) -> None:
    def handler(run: Run) -> Callable[[Job], Artifacts]:
        def handle(job: Job) -> Artifacts:
            require_enabled(settings)
            engine = create_engine(settings)
            try:
                return run(settings, engine, job, clock())
            finally:
                engine.dispose()

        return handle

    registry.register(CATALOG_KIND, handler(run_catalog))
    registry.register(TRANSCRIPTS_KIND, handler(run_transcripts))
    registry.register(CALENDAR_KIND, handler(run_calendar))
    registry.register(PRICES_KIND, handler(run_prices))
