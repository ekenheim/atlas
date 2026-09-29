"""`/api/v1/queue`: the queue-level pause, the backfill window and pending jobs by kind."""

from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel

from atlas.jobs import JobQueue, QueuePause


class BackfillWindowStatus(BaseModel):
    window: str | None  # "HH:MM-HH:MM" local time; None: backfill jobs run at any time
    timezone: str | None
    open: bool  # backfill-class jobs may be claimed now
    next_open_at: datetime | None  # when it next opens, while closed


class PendingKind(BaseModel):
    kind: str
    queued: int
    running: int
    backfill_queued: int  # of the queued jobs, those of backfill class
    paused: bool  # held back by the pause now


class QueueStatus(BaseModel):
    now: datetime
    pause: QueuePause
    backfill_window: BackfillWindowStatus
    pending: list[PendingKind]


def queue_router(queue: JobQueue) -> APIRouter:
    router = APIRouter(prefix="/api/v1/queue", tags=["queue"])

    @router.get("", response_model=QueueStatus)
    def get_queue() -> QueueStatus:  # pyright: ignore[reportUnusedFunction]
        return queue_status(queue)

    return router


def queue_status(queue: JobQueue) -> QueueStatus:
    now = queue.clock()
    pause = queue.pause_state()
    window = queue.pacing.backfill_window
    is_open = queue.pacing.window_open(now)
    by_kind: dict[str, PendingKind] = {}
    for group in queue.pending():
        entry = by_kind.setdefault(
            group.kind,
            PendingKind(
                kind=group.kind,
                queued=0,
                running=0,
                backfill_queued=0,
                paused=pause.paused and group.kind in pause.kinds,
            ),
        )
        if group.status == "running":
            entry.running += group.count
        else:
            entry.queued += group.count
            if group.job_class == "backfill":
                entry.backfill_queued += group.count
    return QueueStatus(
        now=now,
        pause=pause,
        backfill_window=BackfillWindowStatus(
            window=window.spec if window else None,
            timezone=window.timezone.key if window else None,
            open=is_open,
            next_open_at=None if is_open or window is None else window.next_open(now),
        ),
        pending=[by_kind[kind] for kind in sorted(by_kind)],
    )
