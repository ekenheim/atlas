"""The Chokepoint Watch's board (Chokepoint Watch ticket W1) and its run record.

A `chokepoint` is one candidate bottleneck; its state is the fold of its insert-only
`chokepoint_event` rows (`fold`), so what changed, why, on what evidence and in which session is
never lost, and a killed chokepoint stays listed. `watch_run` is one run of the Watch, with its
memo. Every write is audited (`chokepoint.created|updated`, `watch_run.created`).
`docs/decisions.md`, "The board is the fold of its events".
"""

from atlas.chokepoints.model import (
    PROSPECTIVE_WINDOW,
    STALE_AFTER,
    Chokepoint,
    ChokepointCreate,
    ChokepointDetail,
    ChokepointError,
    ChokepointEvent,
    EventCreate,
    WatchRun,
    WatchRunCreate,
    fold,
)
from atlas.chokepoints.service import (
    Chokepoints,
    WatchRuns,
    check_read_session,
    get_chokepoint,
    get_watch_run,
    list_chokepoints,
    list_watch_runs,
)

__all__ = [
    "PROSPECTIVE_WINDOW",
    "STALE_AFTER",
    "Chokepoint",
    "ChokepointCreate",
    "ChokepointDetail",
    "ChokepointError",
    "ChokepointEvent",
    "Chokepoints",
    "EventCreate",
    "WatchRun",
    "WatchRunCreate",
    "WatchRuns",
    "check_read_session",
    "fold",
    "get_chokepoint",
    "get_watch_run",
    "list_chokepoints",
    "list_watch_runs",
]
