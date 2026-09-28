"""The retention job handlers: `retain`, `poll_operation` and `reprocess`."""

from collections.abc import Callable, Generator
from contextlib import contextmanager

from sqlalchemy import create_engine

from atlas.archive import open_archive
from atlas.audit import Actor
from atlas.companies import load_universe
from atlas.hindsight import HindsightGateway
from atlas.jobs.handlers import HandlerRegistry
from atlas.jobs.queue import Artifacts, Job
from atlas.retention.service import (
    POLL_KIND,
    REPROCESS_KIND,
    RETAIN_KIND,
    OperationPayload,
    RetainPayload,
    RetainTimings,
    Retention,
)
from atlas.settings import Settings


class HindsightNotConfigured(Exception):
    """A retention job ran without ATLAS_HINDSIGHT_URL."""


def register_retention_handlers(registry: HandlerRegistry, settings: Settings) -> None:
    def retain(job: Job) -> Artifacts:
        payload = RetainPayload.model_validate(job.payload)
        with _retention(settings) as retention:
            return retention.retain(payload.source_version_id, job.id)

    def poll(job: Job) -> Artifacts:
        payload = OperationPayload.model_validate(job.payload)
        with _retention(settings) as retention:
            return retention.poll(payload.operation_id)

    def reprocess(job: Job) -> Artifacts:
        payload = OperationPayload.model_validate(job.payload)
        with _retention(settings) as retention:
            return retention.reprocess(payload.operation_id, job.id)

    handlers: dict[str, Callable[[Job], Artifacts]] = {
        RETAIN_KIND: retain,
        POLL_KIND: poll,
        REPROCESS_KIND: reprocess,
    }
    for kind, handler in handlers.items():
        registry.register(kind, handler)


@contextmanager
def _retention(settings: Settings) -> Generator[Retention]:
    gateway = HindsightGateway.from_settings(settings)
    if gateway is None:
        raise HindsightNotConfigured("Hindsight is not configured (ATLAS_HINDSIGHT_URL)")
    engine = create_engine(settings.database_url, pool_pre_ping=True)
    try:
        yield Retention(
            engine,
            open_archive(settings),
            gateway,
            Actor.from_settings(settings),
            load_universe(settings.themes_config),
            RetainTimings(
                poll_timeout=settings.retain_poll_timeout_seconds,
                poll_interval=settings.retain_poll_interval_seconds,
                poll_attempts=settings.retain_poll_attempts,
            ),
        )
    finally:
        gateway.close()
        engine.dispose()
