"""The retention job handlers: `retain`, `poll_operation`, `reprocess`, `memory_backfill`,
`triage` and `triage_audit`."""

import uuid
from collections.abc import Callable, Generator
from contextlib import contextmanager

from atlas.archive import open_archive
from atlas.audit import Actor
from atlas.companies import extend_universe, load_universe
from atlas.jobs.handlers import HandlerRegistry
from atlas.jobs.queue import Artifacts, Job
from atlas.jobs.resources import hindsight_resources, run_recorder
from atlas.retention.audit import AUDIT_KIND, TriageAuditor
from atlas.retention.backfill import BACKFILL_KIND, Backfill, BackfillPayload
from atlas.retention.service import (
    POLL_KIND,
    REPROCESS_KIND,
    RETAIN_KIND,
    TRIAGE_KIND,
    OperationPayload,
    RetainPayload,
    RetainTimings,
    Retention,
)
from atlas.retention.triage import Triage
from atlas.roles import RoleCaller
from atlas.settings import Settings


def register_retention_handlers(registry: HandlerRegistry, settings: Settings) -> None:
    def retain(job: Job) -> Artifacts:
        payload = RetainPayload.model_validate(job.payload)
        with _retention(settings) as retention:
            return retention.retain(payload.source_version_id, job.id, job.job_class)

    def poll(job: Job) -> Artifacts:
        payload = OperationPayload.model_validate(job.payload)
        with _retention(settings) as retention:
            return retention.poll(payload.operation_id, job.id)

    def reprocess(job: Job) -> Artifacts:
        payload = OperationPayload.model_validate(job.payload)
        with _retention(settings) as retention:
            return retention.reprocess(payload.operation_id, job.id)

    def backfill(job: Job) -> Artifacts:
        payload = BackfillPayload.model_validate(job.payload)
        with hindsight_resources(settings) as (gateway, engine):
            return Backfill(engine, gateway, Actor.from_settings(settings)).run(payload, job)

    def triage(job: Job) -> Artifacts:
        payload = RetainPayload.model_validate(job.payload)
        with (
            hindsight_resources(settings) as (_, engine),
            run_recorder(settings, engine) as runs,
        ):
            with engine.connect() as connection:
                universe = extend_universe(connection, load_universe(settings.themes_config))
            caller = RoleCaller.from_settings(settings, engine)
            try:
                return Triage(
                    engine,
                    open_archive(settings),
                    Actor.from_settings(settings),
                    universe,
                    caller,
                    runs,
                    excerpt_chars=settings.triage_excerpt_chars,
                    windows_per_section=settings.triage_windows_per_section,
                    sections_per_call=settings.triage_sections_per_call,
                    window_overlap_chars=settings.triage_window_overlap_chars,
                ).triage(payload.source_version_id, job.job_class)
            finally:
                if caller is not None:
                    caller.close()

    def triage_audit(job: Job) -> Artifacts:
        with (
            hindsight_resources(settings) as (_, engine),
            run_recorder(settings, engine) as runs,
        ):
            with engine.connect() as connection:
                universe = extend_universe(connection, load_universe(settings.themes_config))
            caller = RoleCaller.from_settings(settings, engine)
            try:
                return TriageAuditor(
                    engine,
                    open_archive(settings),
                    Actor.from_settings(settings),
                    universe,
                    caller,
                    runs,
                    samples_per_attempt=settings.triage_audit_samples_per_attempt,
                ).run(uuid.UUID(str(job.payload["triage_audit_id"])))
            finally:
                if caller is not None:
                    caller.close()

    handlers: dict[str, Callable[[Job], Artifacts]] = {
        RETAIN_KIND: retain,
        POLL_KIND: poll,
        REPROCESS_KIND: reprocess,
        BACKFILL_KIND: backfill,
        TRIAGE_KIND: triage,
        AUDIT_KIND: triage_audit,
    }
    # All depend on Hindsight or LiteLLM (the retains on Hindsight and, through it, LiteLLM;
    # triage and its audit on LiteLLM): a quota or outage failure pauses them together
    # (atlas.jobs.pacing).
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
                transient_retries=settings.retain_transient_retries,
            ),
            triage=settings.triage_enabled(),
            extractor=settings.retain_extractor,
        )
