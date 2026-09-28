"""Job handlers, registered by job kind."""

from collections.abc import Callable

from atlas.jobs.queue import Artifacts, Job

# A handler does the work for one attempt and returns the artifacts it produced (e.g. the
# IDs of new Source Versions). Raising records a failed attempt, retried up to the bound.
JobHandler = Callable[[Job], Artifacts | None]


class HandlerRegistry:
    def __init__(self) -> None:
        self._handlers: dict[str, JobHandler] = {}

    def register(self, kind: str, handler: JobHandler) -> None:
        if kind in self._handlers:
            raise ValueError(f"a handler for job kind {kind!r} is already registered")
        self._handlers[kind] = handler

    def get(self, kind: str) -> JobHandler | None:
        return self._handlers.get(kind)

    def kinds(self) -> list[str]:
        return sorted(self._handlers)


def noop(job: Job) -> Artifacts:
    """Does nothing; exercises the queue end to end."""
    return {}


def builtin_registry() -> HandlerRegistry:
    """Every job kind Atlas knows how to run; `atlas worker` uses this registry."""
    registry = HandlerRegistry()
    registry.register("noop", noop)
    return registry
