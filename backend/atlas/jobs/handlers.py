"""Job handlers, registered by job kind."""

from collections.abc import Callable
from typing import TYPE_CHECKING

from atlas.jobs.queue import Artifacts, Job

if TYPE_CHECKING:
    from atlas.settings import Settings

# A handler does the work for one attempt and returns the artifacts it produced (e.g. the
# IDs of new Source Versions). Raising records a failed attempt, retried up to the bound.
JobHandler = Callable[[Job], Artifacts | None]


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


def builtin_registry(settings: "Settings | None" = None) -> HandlerRegistry:
    """Every job kind Atlas knows how to run; `atlas worker` uses this registry.

    Kinds that touch the database, the archive, sources or Hindsight (`ingest`, `retain`,
    `poll_operation`, `reprocess`, `reflect`) need `settings`.
    """
    registry = HandlerRegistry()
    registry.register("noop", noop)
    if settings is not None:
        from atlas.ledger.ingest import INGEST_KIND, make_ingest_handler
        from atlas.research import register_research_handlers
        from atlas.retention import register_retention_handlers

        registry.register(INGEST_KIND, make_ingest_handler(settings))
        register_retention_handlers(registry, settings)
        register_research_handlers(registry, settings)
    return registry
