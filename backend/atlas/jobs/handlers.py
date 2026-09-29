"""Job handlers, registered by job kind."""

from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING

from atlas.jobs.pacing import Clock, utc_now
from atlas.jobs.queue import Artifacts, Job

if TYPE_CHECKING:
    from sqlalchemy import Engine

    from atlas.settings import Settings

# A handler does the work for one attempt and returns the artifacts it produced (e.g. the
# IDs of new Source Versions). Raising records a failed attempt, retried up to the bound.
JobHandler = Callable[[Job], Artifacts | None]
# A schedule enqueues the jobs that are due at the given time (idempotently); the worker
# calls each of its schedules at the start of every pass, with the queue's pacing clock.
Schedule = Callable[[datetime], object]


class HandlerRegistry:
    def __init__(self) -> None:
        self._handlers: dict[str, JobHandler] = {}
        self._pausable: set[str] = set()

    def register(self, kind: str, handler: JobHandler, *, pausable: bool = False) -> None:
        """Register `kind`. A pausable kind depends on Hindsight or LiteLLM: its quota or
        outage failures pause the queue, and a pause holds back every pausable kind."""
        if kind in self._handlers:
            raise ValueError(f"a handler for job kind {kind!r} is already registered")
        self._handlers[kind] = handler
        if pausable:
            self._pausable.add(kind)

    def get(self, kind: str) -> JobHandler | None:
        return self._handlers.get(kind)

    def kinds(self) -> list[str]:
        return sorted(self._handlers)

    def pausable(self, kind: str) -> bool:
        return kind in self._pausable

    def pausable_kinds(self) -> list[str]:
        return sorted(self._pausable)


def noop(job: Job) -> Artifacts:
    """Does nothing; exercises the queue end to end."""
    return {}


def builtin_registry(
    settings: "Settings | None" = None, *, clock: Clock = utc_now
) -> HandlerRegistry:
    """Every job kind Atlas knows how to run; `atlas worker` uses this registry.

    Kinds that touch the database, the archive, sources or Hindsight (`ingest`, `retain`,
    `poll_operation`, `reprocess`, `reflect`, `refresh_mental_model`, `extract_claims`,
    `review_relationships`, `discover`,
    `investigation_task`, `propose_candidates`) need
    `settings`.
    `clock` is the application clock of handlers that measure time (a mental model's
    minimum refresh interval).
    """
    registry = HandlerRegistry()
    registry.register("noop", noop)
    if settings is not None:
        from atlas.candidates import register_candidate_handlers
        from atlas.claims import register_claim_handlers
        from atlas.discovery import register_discovery_handlers
        from atlas.investigations import register_investigation_handlers
        from atlas.ledger.ingest import INGEST_KIND, make_ingest_handler
        from atlas.mental_models import register_mental_model_handlers
        from atlas.relationships import register_relationship_handlers
        from atlas.research import register_research_handlers
        from atlas.retention import register_retention_handlers

        registry.register(INGEST_KIND, make_ingest_handler(settings))
        register_retention_handlers(registry, settings)
        register_research_handlers(registry, settings)
        register_mental_model_handlers(registry, settings, clock)
        register_claim_handlers(registry, settings)
        register_relationship_handlers(registry, settings)
        register_discovery_handlers(registry, settings)
        register_investigation_handlers(registry, settings)
        register_candidate_handlers(registry, settings)
    return registry


def builtin_schedules(settings: "Settings", engine: "Engine") -> list[Schedule]:
    """The schedules `atlas worker` runs: the daily mental model refreshes."""
    from atlas.mental_models import refresh_schedules

    return refresh_schedules(settings, engine)
