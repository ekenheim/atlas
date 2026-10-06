"""Atlas decides when Memory consolidates (memory-quality ticket 19; `docs/decisions.md`, "Atlas
decides when Memory consolidates"), and follows each run to its end, counted by rounds (ticket
20).

The research bank's template turns Hindsight's automatic consolidation off
(`enable_auto_consolidation: false`), so observations are formed only when Atlas asks:

- **The job.** `consolidate` (pausable; provider `hindsight_consolidation`, one unit per
  round) decides, then asks Hindsight to consolidate the research bank
  (`POST .../consolidate`), records the operation and follows the run to its end, bounded by
  `ATLAS_CONSOLIDATE_POLL_TIMEOUT_SECONDS`. A run still going at the bound stays recorded as
  running (`submitted`); the job ends with outcome `running`, and the next job follows that
  run instead of submitting another.
- **Rounds.** Hindsight consolidates a run in rounds: one operation consolidates at most a
  round's memories, and when it ends with memories still pending Hindsight submits the next
  round as a new operation by itself. A run's rounds are the operation Atlas requested and
  every consolidation operation of the bank created after it (`GET .../operations?type=
  consolidation`), each recorded once (`memory_consolidation_round`) and counted once against
  the `hindsight_consolidation` budget when Atlas first sees it. A run is `completed` only
  when none of its rounds is pending or processing and the last one ended `completed`; the
  bank's `pending_consolidation` (`GET .../stats`) is recorded then.
- **Stopped at the budget.** While a round of the run is pending or processing and the rounds
  counted in the window reach the limit the job's class may use, Atlas cancels it
  (`DELETE .../operations/{id}`; no round follows a cancelled one) and records the run
  `stopped_at_budget`; the next try asks again once the window allows (consolidation is
  incremental).
- **Never twice for the same work.** The decision is taken under a per-bank advisory lock:
  a run of the bank still `submitted` in Atlas's record is followed, not resubmitted
  (`joined`); a consolidation of the bank Atlas did not request, pending or processing, is
  left alone (`other_consolidation_running`: neither counted nor cancelled, and nothing is
  submitted beside it, so the rounds after Atlas's request are its own);
  nothing is submitted while a retain's operation may be in Hindsight: a `retain` or
  `reprocess` job running, or a `poll_operation` job queued or running (`retains_pending`).
  A retain still queued has sent nothing, so a backfill's retains waiting behind their budget
  or window for days don't hold it (0.4.2). Nor is anything submitted when no
  section was retained since the last completed consolidation (`nothing_retained`). The
  database allows one `submitted` row per bank.
- **Followed every few minutes.** While a run is still going, the worker enqueues a
  follow-up job `ATLAS_CONSOLIDATE_FOLLOW_SECONDS` after the last consolidate job decided
  (`ConsolidationFollow`): it only follows the run, counts no daily try and ends with the run,
  so the rounds Hindsight runs unwatched between two looks are at most one interval's.
- **When.** The worker's schedule enqueues one backfill-class job a day from
  `ATLAS_CONSOLIDATE_AT` (UTC; before the mental models' refresh), keyed by the bank, the day
  and the try; a try that waited for retains, or found a run still going, is followed by the
  next an hour after it decided, at most `ATLAS_CONSOLIDATE_MAX_TRIES` a day. By hand:
  `atlas memory consolidate [--key K]`.
- **The record.** Every decision is a `memory_consolidation` row (skipped, submitted,
  completed, failed, stopped_at_budget, with its rounds, the last round followed and the
  bank's `pending_consolidation` at its end); a submitted request and its end are audited.
  `GET /api/v1/memory/health` shows the last requested and last completed run and the
  sections retained since (`consolidation_record`).

Replay and evaluation banks are unchanged: they keep the server's default and the replay asks
for consolidation itself (`atlas.replay`).
"""

import json
import time as _time
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue
from sqlalchemy import Connection, Engine, RowMapping, text

from atlas.audit import Actor, content_hash, record
from atlas.hindsight import (
    HindsightGateway,
    HindsightHTTPError,
    HindsightNotFound,
    ListedOperation,
    Operation,
)
from atlas.jobs.budget import Budgets, Provider, window_usage
from atlas.jobs.handlers import HandlerRegistry, Schedule
from atlas.jobs.pacing import Clock, JobClass, TransientFailure, utc_now
from atlas.jobs.queue import Artifacts, Enqueued, Job, JobQueue, job_id_for
from atlas.jobs.resources import hindsight_resources
from atlas.retention.service import POLL_KIND, REPROCESS_KIND, RETAIN_KIND, operation_error_class
from atlas.settings import Settings

CONSOLIDATE_KIND = "consolidate"
# The jobs that submit retains into the bank: while one is running, no consolidation.
SUBMITTING_KINDS = (RETAIN_KIND, REPROCESS_KIND)
# A scheduled try with one of these outcomes is followed by another, an hour later (one
# stopped at the budget waits in the queue until the window allows it).
RETRY_OUTCOMES = frozenset(
    {"retains_pending", "running", "stopped_at_budget", "other_consolidation_running"}
)
RETRY_AFTER = timedelta(hours=1)
# The budget a run's rounds count against (memory-quality ticket 20).
ROUNDS_PROVIDER: Provider = "hindsight_consolidation"
# The bank's consolidation operations are listed a page at a time, newest first, until the
# run's first round is reached.
LISTING_PAGE = 100
LISTING_MAX_PAGES = 20
_RUNNING = frozenset({"pending", "processing"})

type ConsolidationStatus = Literal[
    "skipped", "submitted", "completed", "failed", "stopped_at_budget"
]
type SkipReason = Literal[
    "nothing_retained", "retains_pending", "consolidation_off", "other_consolidation_running"
]


class ConsolidatePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scheduled_for: date | None = None  # the day a scheduled try is for; None: by hand
    attempt: int = Field(default=0, ge=0)  # the day's try, from 0
    # A follow-up of this run (`ConsolidationFollow`): it only follows, never submits.
    follow: uuid.UUID | None = None


def follow_key(bank_id: str, consolidation_id: uuid.UUID, count: int) -> str:
    """The idempotency key of a run's `count`-th follow-up (from 0)."""
    return f"{CONSOLIDATE_KIND}:{bank_id}:follow:{consolidation_id}:{count}"


def consolidate_key(bank_id: str, day: date, attempt: int) -> str:
    """The idempotency key of a day's scheduled try."""
    return f"{CONSOLIDATE_KIND}:{bank_id}:{day.isoformat()}:{attempt}"


def enqueue_consolidation(
    queue: JobQueue,
    key: str,
    *,
    job_class: JobClass = "interactive",
    payload: ConsolidatePayload | None = None,
) -> Enqueued:
    """Ask for a consolidation of the research bank (idempotent per key)."""
    body = (payload or ConsolidatePayload()).model_dump(mode="json")
    return queue.enqueue(CONSOLIDATE_KIND, key, body, job_class=job_class)


@dataclass(frozen=True)
class ConsolidationTimings:
    poll_timeout: float = 240.0  # below the job lease; a run still going is followed later
    poll_interval: float = 5.0


class ConsolidationSchedule:
    """Enqueues the day's consolidation from `at` (UTC), and its next try an hour after one
    that waited, at most `max_tries` a day."""

    def __init__(
        self,
        engine: Engine,
        bank_id: str,
        at: time,
        max_tries: int,
        retry_after: timedelta = RETRY_AFTER,
    ) -> None:
        self._engine = engine
        self._bank_id = bank_id
        self._at = at
        self._max_tries = max_tries
        self._retry_after = retry_after
        self._finished: date | None = None

    def __call__(self, now: datetime) -> list[Enqueued]:
        moment = now.astimezone(UTC)
        day = moment.date()
        if self._finished == day or moment.time() < self._at:
            return []
        queue = JobQueue(self._engine)  # audited as the system actor's: Atlas schedules it
        previous: Job | None = None
        for attempt in range(self._max_tries):
            key = consolidate_key(self._bank_id, day, attempt)
            job = queue.get(job_id_for(CONSOLIDATE_KIND, key))
            if job is None:
                if previous is not None and moment < _decided_at(previous) + self._retry_after:
                    return []
                payload = ConsolidatePayload(scheduled_for=day, attempt=attempt)
                return [enqueue_consolidation(queue, key, job_class="backfill", payload=payload)]
            if job.status in ("queued", "running"):
                return []
            if job.status == "failed" or _retry_reason(job) not in RETRY_OUTCOMES:
                break
            previous = job
        self._finished = day
        return []


def _retry_reason(job: Job) -> str | None:
    """Why a finished try may be followed: it waited for retains, or a run was still going."""
    outcome = job.artifacts.get("outcome")
    if outcome == "skipped":
        return str(job.artifacts.get("reason"))
    return str(outcome) if outcome is not None else None


def _decided_at(job: Job) -> datetime:
    decided = job.artifacts.get("decided_at")
    if isinstance(decided, str):
        return datetime.fromisoformat(decided)
    return job.finished_at or job.updated_at


class ConsolidationFollow:
    """While a run of the bank is still going (`submitted`), enqueues a follow-up
    `consolidate` job `every` after the last consolidate job decided, so the run's rounds are
    seen (counted, and cancelled at the budget) within one interval, not at the next hourly
    try (memory-quality ticket 20). A follow-up only follows the run; it has the class of the
    job that requested the run, is keyed by the run and a counter, and is no daily try (it
    counts against no `ATLAS_CONSOLIDATE_MAX_TRIES` and is bound to no day). None is enqueued
    while a consolidate job is queued or running (that one follows the run itself)."""

    def __init__(self, engine: Engine, bank_id: str, every: timedelta) -> None:
        self._engine = engine
        self._bank_id = bank_id
        self._every = every

    def __call__(self, now: datetime) -> list[Enqueued]:
        with self._engine.connect() as connection:
            run = (
                connection.execute(
                    text(
                        "SELECT c.id, coalesce(j.job_class, 'backfill') AS job_class"
                        " FROM memory_consolidation c LEFT JOIN job j ON j.id = c.job_id"
                        " WHERE c.bank_id = :bank AND c.status = 'submitted'"
                    ),
                    {"bank": self._bank_id},
                )
                .mappings()
                .one_or_none()
            )
            if run is None:
                return []
            looked = connection.execute(
                text(
                    "SELECT bool_or(status IN ('queued', 'running')) AS busy,"
                    " max(CAST(coalesce(artifacts->>'looked_at', artifacts->>'decided_at')"
                    "   AS timestamptz)) AS looked_at,"
                    " count(*) FILTER (WHERE payload->>'follow' = :run) AS follows"
                    " FROM job WHERE kind = :kind"
                ),
                {"kind": CONSOLIDATE_KIND, "run": str(run["id"])},
            ).one()
        if looked.busy or (looked.looked_at is not None and now < looked.looked_at + self._every):
            return []
        queue = JobQueue(self._engine)  # audited as the system actor's: Atlas follows it
        key = follow_key(self._bank_id, run["id"], int(looked.follows))
        payload = ConsolidatePayload(follow=run["id"])
        return [enqueue_consolidation(queue, key, job_class=run["job_class"], payload=payload)]


class Consolidation:
    """The `consolidate` job for the research bank."""

    def __init__(
        self,
        engine: Engine,
        gateway: HindsightGateway,
        actor: Actor,
        *,
        clock: Clock = utc_now,
        timings: ConsolidationTimings | None = None,
        enabled: bool = True,
        budgets: Budgets | None = None,
        monotonic: Callable[[], float] = _time.monotonic,
        sleep: Callable[[float], None] = _time.sleep,
    ) -> None:
        self._enabled = enabled
        self._engine = engine
        self._gateway = gateway
        self._actor = actor
        self._clock = clock
        self._timings = timings or ConsolidationTimings()
        self._budgets = budgets  # None: no rounds budget stops a run
        self._monotonic = monotonic
        self._sleep = sleep

    @property
    def bank_id(self) -> str:
        return self._gateway.bank_id

    def run(self, payload: ConsolidatePayload, job: Job) -> Artifacts:
        artifacts = self._run(payload, job)
        # When this job last looked at the run: its follow-up is timed from here.
        return artifacts | {"looked_at": self._clock().isoformat()}

    def _run(self, payload: ConsolidatePayload, job: Job) -> Artifacts:
        decided_at = self._clock()
        base: Artifacts = {"decided_at": decided_at.isoformat()}
        if payload.follow is not None:
            return base | self._follow_up(payload.follow, job)
        latest = self._latest_for_job(job.id)
        if latest is not None and latest["status"] == "submitted":
            return base | self._follow(latest, job)  # an earlier attempt submitted it
        if latest is not None and (
            latest["status"] in ("skipped", "completed", "stopped_at_budget")
            or latest["error_class"] == "permanent"
        ):
            return base | {
                "outcome": f"already_{latest['status']}",
                "consolidation_id": str(latest["id"]),
            }
        # First attempt, or this job's request failed for quota or availability (the pause
        # has lifted): decide afresh.
        row, joined = self._decide(payload, job)
        if row["status"] == "skipped":
            return base | {
                "outcome": "skipped",
                "reason": row["skip_reason"],
                "consolidation_id": str(row["id"]),
                "sections_retained": row["sections_retained"],
            }
        return base | {"joined": joined} | self._follow(row, job)

    # --- deciding ------------------------------------------------------------------------------

    def _decide(self, payload: ConsolidatePayload, job: Job) -> tuple[RowMapping, bool]:
        """The row to follow: a run of the bank still going (joined), a new request, or a
        skip. Taken under the bank's lock, so two jobs never submit two requests."""
        with self._engine.begin() as connection:
            connection.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
                {"key": f"memory_consolidation:{self.bank_id}"},
            )
            running = (
                connection.execute(
                    text(
                        "SELECT * FROM memory_consolidation"
                        " WHERE bank_id = :bank AND status = 'submitted'"
                    ),
                    {"bank": self.bank_id},
                )
                .mappings()
                .one_or_none()
            )
            if running is not None:
                return running, True
            since = sections_retained_since(connection, self.bank_id)
            fields: dict[str, object] = {
                "job_id": job.id,
                "scheduled_for": payload.scheduled_for,
                "sections_retained": since,
            }
            reason: SkipReason | None = None
            if not self._enabled:
                reason = "consolidation_off"
            elif _retains_pending(connection):
                reason = "retains_pending"
            elif since == 0:
                reason = "nothing_retained"
            elif self._other_running():
                reason = "other_consolidation_running"
            if reason is not None:
                skipped = self._insert(connection, fields | {"status": "skipped", "reason": reason})
                return skipped, False
            submitted = self._gateway.consolidate()
            row = self._insert(
                connection,
                fields
                | {
                    "status": "submitted",
                    "operation_id": submitted.operation_id,
                    "deduplicated": submitted.deduplicated,
                    "operation_status": submitted.status,
                },
            )
            self._audit(connection, "memory_consolidation.submitted", None, row)
            return row, False

    def _other_running(self) -> bool:
        """A consolidation of the bank is pending or processing that Atlas did not request
        (no run of Atlas's is `submitted`): someone else's chain, left alone."""
        return any(
            self._gateway.consolidation_operations(status=status, limit=1).operations
            for status in ("processing", "pending")
        )

    def _insert(self, connection: Connection, fields: dict[str, object]) -> RowMapping:
        skipped = fields["status"] == "skipped"
        return (
            connection.execute(
                text(
                    "INSERT INTO memory_consolidation (id, bank_id, job_id, scheduled_for,"
                    " status, skip_reason, operation_id, deduplicated, operation_status,"
                    " sections_retained, completed_at)"
                    " VALUES (:id, :bank, :job_id, :scheduled_for, :status, :reason,"
                    " :operation_id, :deduplicated, :operation_status, :sections_retained,"
                    " CASE WHEN :skipped THEN now() END) RETURNING *"
                ),
                {
                    "id": uuid.uuid4(),
                    "bank": self.bank_id,
                    "reason": None,
                    "operation_id": None,
                    "deduplicated": False,
                    "operation_status": None,
                    **fields,
                    "skipped": skipped,
                },
            )
            .mappings()
            .one()
        )

    def _follow_up(self, consolidation_id: uuid.UUID, job: Job) -> Artifacts:
        """A follow-up: follow the run while it is still going; never submit."""
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    text("SELECT * FROM memory_consolidation WHERE id = :id"),
                    {"id": consolidation_id},
                )
                .mappings()
                .one()
            )
        if row["status"] != "submitted":
            return {
                "outcome": "follow_ended",
                "consolidation_id": str(row["id"]),
                "run_status": row["status"],
            }
        return {"follow": True} | self._follow(row, job)

    # --- following the run -----------------------------------------------------------------------

    def _follow(self, row: RowMapping, job: Job) -> Artifacts:
        """Follow the run's rounds until none is pending or processing, bounded per attempt;
        stop it when the window's rounds are spent."""
        operation_id: str = row["operation_id"]
        base: Artifacts = {"consolidation_id": str(row["id"]), "operation_id": operation_id}
        deadline = self._monotonic() + self._timings.poll_timeout
        while True:
            try:
                rounds = self._rounds(row)
            except HindsightNotFound as error:
                # Pruned or never known to the server: nothing is running any more.
                message = f"Hindsight has no operation {operation_id}: {error}"
                self._update(
                    row,
                    "status = 'failed', error = :error, error_class = 'permanent',"
                    " completed_at = now()",
                    {"error": message[:2000]},
                    action="memory_consolidation.failed",
                )
                return base | {"outcome": "failed", "error": message}
            counted = self._record_rounds(row, rounds)
            last = rounds[-1]
            followed: Artifacts = base | {"rounds": counted, "last_operation_id": last.id}
            running = [r for r in rounds if r.status in _RUNNING]
            if running:
                if self._rounds_spent(job):
                    return followed | self._stop(row, running)
                remaining = deadline - self._monotonic()
                if remaining <= 0:
                    # Bounded: the run stays recorded as running and the next job follows it.
                    return followed | {"outcome": "running", "operation_status": last.status}
                self._sleep(min(self._timings.poll_interval, remaining))
                continue
            if last.status == "completed":
                pending = self._gateway.bank_stats().pending_consolidation
                self._update(
                    row,
                    "status = 'completed', operation_status = :status,"
                    " pending_consolidation = :pending, completed_at = now()",
                    {"status": last.status, "pending": pending},
                    action="memory_consolidation.completed",
                )
                return followed | {"outcome": "completed", "pending_consolidation": pending}
            try:
                operation = self._gateway.operation(last.id)
            except HindsightNotFound as error:
                operation = Operation(
                    operation_id=last.id, status=last.status, error_message=str(error)
                )
            return followed | self._failed(row, operation)

    def _rounds(self, row: RowMapping) -> list[ListedOperation]:
        """The run's rounds, oldest first: the operation Atlas requested and every
        consolidation operation of the bank Hindsight created after it.

        Raises `HindsightNotFound` when Hindsight knows the requested operation no more."""
        requested: str = row["operation_id"]
        seen: list[ListedOperation] = []
        anchor: ListedOperation | None = None
        for page in range(LISTING_MAX_PAGES):
            listing = self._gateway.consolidation_operations(
                limit=LISTING_PAGE, offset=page * LISTING_PAGE
            )
            seen += listing.operations
            anchor = next((o for o in listing.operations if o.id == requested), None)
            if anchor is not None or len(listing.operations) < LISTING_PAGE:
                break
        if anchor is None:  # not listed (pruned from the listing, or beyond it): read it
            found = self._gateway.operation(requested)
            anchor = ListedOperation.model_validate(
                {
                    "id": found.operation_id,
                    "operation_type": found.operation_type,
                    "status": found.status,
                    "created_at": found.created_at,
                    "updated_at": found.updated_at,
                }
            )
        start = anchor.created_at
        chained = [
            o
            for o in seen
            if o.id != requested
            and o.created_at is not None
            and start is not None
            and o.created_at > start
        ]
        return [anchor, *sorted(chained, key=lambda o: (o.created_at, o.id))]

    def _record_rounds(self, row: RowMapping, rounds: Sequence[ListedOperation]) -> int:
        """Record each round once (its first sighting counts it against the budget) and its
        last status; the run's round count."""
        seen_at = self._clock()
        with self._engine.begin() as connection:
            for found in rounds:
                connection.execute(
                    text(
                        "INSERT INTO memory_consolidation_round (operation_id, consolidation_id,"
                        " status, created_at, first_seen_at) VALUES (:operation, :run, :status,"
                        " :created, :seen) ON CONFLICT (operation_id) DO UPDATE"
                        " SET status = EXCLUDED.status, updated_at = now()"
                        " WHERE memory_consolidation_round.consolidation_id"
                        "   = EXCLUDED.consolidation_id"
                    ),
                    {
                        "operation": found.id,
                        "run": row["id"],
                        "status": found.status,
                        "created": found.created_at,
                        "seen": seen_at,
                    },
                )
            counted = int(
                connection.execute(
                    text(
                        "SELECT count(*) FROM memory_consolidation_round"
                        " WHERE consolidation_id = :id"
                    ),
                    {"id": row["id"]},
                ).scalar_one()
            )
            connection.execute(
                text(
                    "UPDATE memory_consolidation SET rounds = :rounds, last_operation_id = :last,"
                    " operation_status = :status, updated_at = now()"
                    " WHERE id = :id AND status = 'submitted'"
                ),
                {
                    "id": row["id"],
                    "rounds": counted,
                    "last": rounds[-1].id,
                    "status": rounds[-1].status,
                },
            )
            return counted

    def _rounds_spent(self, job: Job) -> bool:
        """The rounds counted in the window reached the limit `job`'s class may use."""
        if self._budgets is None:
            return False
        with self._engine.connect() as connection:
            usage = window_usage(connection, self._budgets, self._clock())[ROUNDS_PROVIDER]
        return usage.used >= self._budgets.limit(ROUNDS_PROVIDER, job.job_class)

    def _stop(self, row: RowMapping, running: Sequence[ListedOperation]) -> Artifacts:
        """Cancel the run's running rounds on Hindsight and record it stopped at the budget."""
        cancelled: list[str] = []
        for found in running:
            try:
                self._gateway.cancel_operation(found.id)
            except HindsightHTTPError as error:
                if error.status_code != 409:  # 409: it ended meanwhile
                    raise
            cancelled.append(found.id)
        pending = self._gateway.bank_stats().pending_consolidation
        with self._engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE memory_consolidation_round SET status = 'cancelled',"
                    " updated_at = now() WHERE operation_id = ANY(:cancelled)"
                    " AND consolidation_id = :run"
                ),
                {"cancelled": cancelled, "run": row["id"]},
            )
        self._update(
            row,
            "status = 'stopped_at_budget', operation_status = 'cancelled',"
            " pending_consolidation = :pending, completed_at = now()",
            {"pending": pending},
            action="memory_consolidation.stopped_at_budget",
        )
        return {
            "outcome": "stopped_at_budget",
            "cancelled": list[JsonValue](cancelled),
            "pending_consolidation": pending,
        }

    def _failed(self, row: RowMapping, operation: Operation) -> Artifacts:
        """The run's last round ended failed or cancelled."""
        error = operation.error_message or (
            f"Hindsight reported the consolidation {operation.status} with no error message"
        )
        error_class = operation_error_class(operation)
        self._update(
            row,
            "status = 'failed', operation_status = :status, error = :error,"
            " error_class = :class, result_metadata = CAST(:metadata AS jsonb),"
            " completed_at = now()",
            {
                "status": operation.status,
                "error": error,
                "class": error_class,
                "metadata": json.dumps(operation.result_metadata),
            },
            action="memory_consolidation.failed",
        )
        if error_class != "permanent":
            raise TransientFailure(
                error_class,
                f"Hindsight consolidation {operation.operation_id} {operation.status}"
                f" ({error_class}): {error}",
            )
        return {"outcome": "failed", "error": error}

    # --- rows ----------------------------------------------------------------------------------

    def _latest_for_job(self, job_id: uuid.UUID) -> RowMapping | None:
        with self._engine.connect() as connection:
            return (
                connection.execute(
                    text(
                        "SELECT * FROM memory_consolidation WHERE job_id = :job"
                        " ORDER BY requested_at DESC, updated_at DESC LIMIT 1"
                    ),
                    {"job": job_id},
                )
                .mappings()
                .one_or_none()
            )

    def _update(
        self,
        row: RowMapping,
        assignments: str,
        params: dict[str, object],
        *,
        action: str | None = None,
    ) -> None:
        """Change a running row (once: a row another job already ended stays as it is)."""
        with self._engine.begin() as connection:
            new = (
                connection.execute(
                    text(
                        f"UPDATE memory_consolidation SET {assignments}, updated_at = now()"  # noqa: S608 (constant fragments)
                        " WHERE id = :id AND status = 'submitted' RETURNING *"
                    ),
                    {"id": row["id"], **params},
                )
                .mappings()
                .one_or_none()
            )
            if new is not None and action is not None:
                self._audit(connection, action, row, new)

    def _audit(
        self, connection: Connection, action: str, old: RowMapping | None, new: RowMapping
    ) -> None:
        record(
            connection,
            self._actor,
            action,
            entity_type="memory_consolidation",
            entity_id=str(new["id"]),
            old_hash=content_hash(dict(old)) if old is not None else None,
            new_hash=content_hash(dict(new)),
        )


def _retains_pending(connection: Connection) -> bool:
    """A retain's operation may be in Hindsight (the bank's: Atlas retains into the one
    research bank): a retain or reprocess is running, or a poll of its operation is queued or
    running. A queued retain or reprocess has submitted nothing yet."""
    return bool(
        connection.execute(
            text(
                "SELECT EXISTS (SELECT FROM job WHERE"
                " (kind = ANY(:submitting) AND status = 'running')"
                " OR (kind = :poll AND status IN ('queued', 'running')))"
            ),
            {"submitting": list(SUBMITTING_KINDS), "poll": POLL_KIND},
        ).scalar_one()
    )


def sections_retained_since(connection: Connection, bank_id: str) -> int:
    """Sections of the bank retained (completed) or retired (their facts are deleted, so the
    observations that cited them need rebuilding) since the last completed consolidation was
    requested: what the next one would consolidate. Database times on both sides."""
    return int(
        connection.execute(
            text(
                "SELECT count(*) FROM memory_document m WHERE m.bank_id = :bank"
                " AND m.retain_state IN ('completed', 'retired') AND m.updated_at > coalesce(("
                "   SELECT max(c.requested_at) FROM memory_consolidation c"
                "   WHERE c.bank_id = :bank AND c.status = 'completed'), '-infinity')"
            ),
            {"bank": bank_id},
        ).scalar_one()
    )


# --- the worker's handler and schedule ---------------------------------------------------------


def register_consolidation_handlers(
    registry: HandlerRegistry, settings: Settings, clock: Clock = utc_now
) -> None:
    def consolidate(job: Job) -> Artifacts:
        payload = ConsolidatePayload.model_validate(job.payload)
        with hindsight_resources(settings) as (gateway, engine):
            return Consolidation(
                engine,
                gateway,
                Actor.from_settings(settings),
                clock=clock,
                timings=ConsolidationTimings(
                    poll_timeout=settings.consolidate_poll_timeout_seconds,
                    poll_interval=settings.consolidate_poll_interval_seconds,
                ),
                enabled=settings.consolidation_enabled,
                budgets=Budgets.from_settings(settings),
            ).run(payload, job)

    # Pausable: consolidation is an LLM run on Hindsight's primary model, so quota and
    # outages pause it like a retain.
    registry.register(CONSOLIDATE_KIND, consolidate, pausable=True)


def consolidation_schedules(settings: Settings, engine: Engine) -> list[Schedule]:
    """The follow-ups of a run still going, and the daily consolidation (unless its
    schedule is empty); none when Hindsight or consolidation is off."""
    if not settings.hindsight_url or not settings.consolidation_enabled:
        return []
    every = timedelta(seconds=settings.consolidate_follow_seconds)
    schedules: list[Schedule] = [ConsolidationFollow(engine, settings.hindsight_bank_id, every)]
    if settings.consolidate_at:
        hour, minute = (int(part) for part in settings.consolidate_at.split(":"))
        schedules.append(
            ConsolidationSchedule(
                engine,
                settings.hindsight_bank_id,
                time(hour, minute),
                settings.consolidate_max_tries,
            )
        )
    return schedules


# --- the health read ---------------------------------------------------------------------------


class ConsolidationRun(BaseModel):
    """A consolidation request Atlas submitted to the bank."""

    id: uuid.UUID
    job_id: uuid.UUID | None
    operation_id: str = Field(description="the consolidation operation Atlas requested")
    status: Literal["submitted", "completed", "failed", "stopped_at_budget"] = Field(
        description="submitted: a round of the run is still running, as last seen;"
        " stopped_at_budget: its rounds reached the window's limit and Atlas cancelled it"
    )
    operation_status: str | None = Field(
        description="what Hindsight last reported for the run's last round"
    )
    rounds: int = Field(
        description="the run's rounds counted so far: the operation Atlas requested and each"
        " consolidation operation Hindsight chained after it (memory-quality ticket 20)"
    )
    last_operation_id: str | None = Field(description="the newest round followed")
    pending_consolidation: int | None = Field(
        description="the bank's memories still pending consolidation when the run ended"
        " (completed or stopped); None while it runs and for runs before ticket 20"
    )
    deduplicated: bool = Field(description="Hindsight reused a pending consolidation for it")
    sections_retained: int = Field(
        description="sections retained since the last completed consolidation when it was asked"
    )
    error: str | None
    requested_at: datetime
    completed_at: datetime | None


class ConsolidationRecord(BaseModel):
    last_requested: ConsolidationRun | None
    last_completed: ConsolidationRun | None
    sections_retained_since: int = Field(
        description="sections retained since the last completed consolidation was requested"
    )


def consolidation_record(connection: Connection, bank_id: str) -> ConsolidationRecord:
    def last(condition: str) -> ConsolidationRun | None:
        row = (
            connection.execute(
                text(
                    "SELECT * FROM memory_consolidation WHERE bank_id = :bank"  # noqa: S608 (constant fragments)
                    f" AND {condition} ORDER BY requested_at DESC, id LIMIT 1"
                ),
                {"bank": bank_id},
            )
            .mappings()
            .one_or_none()
        )
        return None if row is None else ConsolidationRun.model_validate(dict(row))

    return ConsolidationRecord(
        last_requested=last("status <> 'skipped'"),
        last_completed=last("status = 'completed'"),
        sections_retained_since=sections_retained_since(connection, bank_id),
    )
