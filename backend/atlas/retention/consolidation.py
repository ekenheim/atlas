"""Atlas decides when Memory consolidates (memory-quality ticket 19; `docs/decisions.md`, "Atlas
decides when Memory consolidates").

The research bank's template turns Hindsight's automatic consolidation off
(`enable_auto_consolidation: false`), so observations are formed only when Atlas asks:

- **The job.** `consolidate` (pausable; provider `codex`, one unit per request Atlas
  submits) decides, then asks Hindsight to consolidate the research bank
  (`POST .../consolidate`), records the operation and polls it to its end, bounded by
  `ATLAS_CONSOLIDATE_POLL_TIMEOUT_SECONDS`. A run still going at the bound stays recorded as
  running (`submitted`); the job ends with outcome `running`, and the next job follows that
  operation instead of submitting another.
- **Never twice for the same work.** The decision is taken under a per-bank advisory lock:
  a consolidation of the bank still running (Atlas's own record: the recorded API has no
  filtered listing of the bank's running operations, and auto-consolidation is off, so the
  only consolidation running is one Atlas asked for) is followed, not resubmitted (`joined`);
  nothing is submitted while a `retain`, `poll_operation` or `reprocess` job is queued or
  running (`retains_pending`: consolidating half a filing is the waste this ends), nor when no
  section was retained since the last completed consolidation (`nothing_retained`). The
  database allows one `submitted` row per bank.
- **When.** The worker's schedule enqueues one backfill-class job a day from
  `ATLAS_CONSOLIDATE_AT` (UTC; before the mental models' refresh), keyed by the bank, the day
  and the try; a try that waited for retains, or found a run still going, is followed by the
  next an hour after it decided, at most `ATLAS_CONSOLIDATE_MAX_TRIES` a day. By hand:
  `atlas memory consolidate [--key K]`.
- **The record.** Every decision is a `memory_consolidation` row (skipped, submitted,
  completed, failed); a submitted request and its end are audited. `GET /api/v1/memory/health`
  shows the last requested and last completed run and the sections retained since
  (`consolidation_record`).

Replay and evaluation banks are unchanged: they keep the server's default and the replay asks
for consolidation itself (`atlas.replay`).
"""

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection, Engine, RowMapping, text

from atlas.audit import Actor, content_hash, record
from atlas.hindsight import HindsightGateway, HindsightNotFound, OperationTimeout
from atlas.jobs.handlers import HandlerRegistry, Schedule
from atlas.jobs.pacing import Clock, JobClass, TransientFailure, utc_now
from atlas.jobs.queue import Artifacts, Enqueued, Job, JobQueue, job_id_for
from atlas.jobs.resources import hindsight_resources
from atlas.retention.service import POLL_KIND, REPROCESS_KIND, RETAIN_KIND, operation_error_class
from atlas.settings import Settings

CONSOLIDATE_KIND = "consolidate"
# The jobs that retain into the bank: while one is queued or running, no consolidation.
RETAIN_JOB_KINDS = (RETAIN_KIND, POLL_KIND, REPROCESS_KIND)
# A scheduled try with one of these outcomes is followed by another, an hour later.
RETRY_OUTCOMES = frozenset({"retains_pending", "running"})
RETRY_AFTER = timedelta(hours=1)

type ConsolidationStatus = Literal["skipped", "submitted", "completed", "failed"]
type SkipReason = Literal["nothing_retained", "retains_pending", "consolidation_off"]


class ConsolidatePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scheduled_for: date | None = None  # the day a scheduled try is for; None: by hand
    attempt: int = Field(default=0, ge=0)  # the day's try, from 0


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
    ) -> None:
        self._enabled = enabled
        self._engine = engine
        self._gateway = gateway
        self._actor = actor
        self._clock = clock
        self._timings = timings or ConsolidationTimings()

    @property
    def bank_id(self) -> str:
        return self._gateway.bank_id

    def run(self, payload: ConsolidatePayload, job: Job) -> Artifacts:
        decided_at = self._clock()
        base: Artifacts = {"decided_at": decided_at.isoformat()}
        latest = self._latest_for_job(job.id)
        if latest is not None and latest["status"] == "submitted":
            return base | self._await(latest)  # an earlier attempt submitted it
        if latest is not None and (
            latest["status"] in ("skipped", "completed") or latest["error_class"] == "permanent"
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
        return base | {"joined": joined} | self._await(row)

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

    # --- following the operation ---------------------------------------------------------------

    def _await(self, row: RowMapping) -> Artifacts:
        operation_id: str = row["operation_id"]
        base: Artifacts = {"consolidation_id": str(row["id"]), "operation_id": operation_id}
        try:
            operation = self._gateway.wait_for_operation(
                operation_id,
                timeout=self._timings.poll_timeout,
                poll_interval=self._timings.poll_interval,
            )
        except OperationTimeout as timeout:
            # Bounded: the run stays recorded as running and the next job follows it.
            self._update(row, "operation_status = :status", {"status": timeout.last_status})
            return base | {"outcome": "running", "operation_status": timeout.last_status}
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
        if operation.succeeded:
            self._update(
                row,
                "status = 'completed', operation_status = :status,"
                " result_metadata = CAST(:metadata AS jsonb), completed_at = now()",
                {"status": operation.status, "metadata": json.dumps(operation.result_metadata)},
                action="memory_consolidation.completed",
            )
            return base | {"outcome": "completed"}
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
                f"Hindsight consolidation {operation_id} {operation.status} ({error_class}):"
                f" {error}",
            )
        return base | {"outcome": "failed", "error": error}

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
    """A retain, a retain poll or a reprocess is queued or running (the bank's: Atlas retains
    into the one research bank)."""
    return bool(
        connection.execute(
            text(
                "SELECT EXISTS (SELECT FROM job WHERE kind = ANY(:kinds)"
                " AND status IN ('queued', 'running'))"
            ),
            {"kinds": list(RETAIN_JOB_KINDS)},
        ).scalar_one()
    )


def sections_retained_since(connection: Connection, bank_id: str) -> int:
    """Sections of the bank retained (completed) since the last completed consolidation was
    requested: what the next one would consolidate. Database times on both sides."""
    return int(
        connection.execute(
            text(
                "SELECT count(*) FROM memory_document m WHERE m.bank_id = :bank"
                " AND m.retain_state = 'completed' AND m.updated_at > coalesce(("
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
            ).run(payload, job)

    # Pausable: consolidation is an LLM run on Hindsight's primary model, so quota and
    # outages pause it like a retain.
    registry.register(CONSOLIDATE_KIND, consolidate, pausable=True)


def consolidation_schedules(settings: Settings, engine: Engine) -> list[Schedule]:
    """The daily consolidation, or none when Hindsight or the schedule is off."""
    if not settings.hindsight_url or not settings.consolidate_at:
        return []
    if not settings.consolidation_enabled:
        return []
    hour, minute = (int(part) for part in settings.consolidate_at.split(":"))
    return [
        ConsolidationSchedule(
            engine, settings.hindsight_bank_id, time(hour, minute), settings.consolidate_max_tries
        )
    ]


# --- the health read ---------------------------------------------------------------------------


class ConsolidationRun(BaseModel):
    """A consolidation request Atlas submitted to the bank."""

    id: uuid.UUID
    job_id: uuid.UUID | None
    operation_id: str
    status: Literal["submitted", "completed", "failed"] = Field(
        description="submitted: its operation is still running, as last polled"
    )
    operation_status: str | None = Field(description="what Hindsight last reported")
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
