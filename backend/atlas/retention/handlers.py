"""The retention job handlers: `retain`, `poll_operation` and `reprocess`."""

from collections.abc import Callable, Generator
from contextlib import contextmanager

from atlas.archive import open_archive
from atlas.audit import Actor
from atlas.companies import extend_universe, load_universe
from atlas.jobs.handlers import HandlerRegistry
from atlas.jobs.queue import Artifacts, Job
from atlas.jobs.resources import hindsight_resources
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


def register_retention_handlers(registry: HandlerRegistry, settings: Settings) -> None:
    def retain(job: Job) -> Artifacts:
        payload = RetainPayload.model_validate(job.payload)
        with _retention(settings) as retention:
            return retention.retain(payload.source_version_id, job.id)

    def poll(job: Job) -> Artifacts:
        payload = OperationPayload.model_validate(job.payload)
        with _retention(settings) as retention:
            return retention.poll(payload.operation_id, job.id)

    def reprocess(job: Job) -> Artifacts:
        payload = OperationPayload.model_validate(job.payload)
        with _retention(settings) as retention:
            return retention.reprocess(payload.operation_id, job.id)

    handlers: dict[str, Callable[[Job], Artifacts]] = {
        RETAIN_KIND: retain,
        POLL_KIND: poll,
        REPROCESS_KIND: reprocess,
    }
    # All three depend on Hindsight (and, through it, LiteLLM): a quota or outage failure
    # pauses them together (atlas.jobs.pacing).
    for kind, handler in handlers.items():
        registry.register(kind, handler, pausable=True)


@contextmanager
def _retention(settings: Settings) -> Generator[Retention]:
    with hindsight_resources(settings) as (gateway, engine):
        with engine.connect() as connection:
            # Committed Candidates' companies are tagged with their themes too.
            universe = extend_universe(connection, load_universe(settings.themes_config))
        yield Retention(
            engine,
            open_archive(settings),
            gateway,
            Actor.from_settings(settings),
            universe,
            RetainTimings(
                poll_timeout=settings.retain_poll_timeout_seconds,
                poll_interval=settings.retain_poll_interval_seconds,
                poll_attempts=settings.retain_poll_attempts,
            ),
        )
