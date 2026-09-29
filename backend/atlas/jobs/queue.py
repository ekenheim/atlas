"""The Postgres job table as a work queue: idempotent enqueue, leased claims, bounded retries.

Lease clocks are the database's (`now()`), so lease expiry means the same thing to every
worker. Pacing (the queue-level pause, the backfill window and the provider budgets,
`atlas.jobs.pacing` and `atlas.jobs.budget`) reads the application clock, which tests can
control.

Audited, in the same transaction as the change: a new job (`job.enqueued`, by the queue's
actor: the configured one, or the system actor for work Atlas schedules itself), and the
queue pause entered and cleared (`queue.paused`, `queue.pause_cleared`). Claims, leases,
retries, requeues and completions are not: they are operational churn, kept in the job
row's own history (`attempts`, `failures`, `lease_owner`, timestamps; docs/decisions.md).
"""

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, JsonValue
from sqlalchemy import Connection, Engine, text

from atlas.audit import SYSTEM_ACTOR, Actor, content_hash, record
from atlas.jobs.budget import (
    PROVIDER_KINDS,
    Holds,
    Provider,
    ProviderBudget,
    holds,
    sweep,
    window_usage,
)
from atlas.jobs.pacing import Clock, FailureClass, JobClass, Pacing, utc_now

JobStatus = Literal["queued", "running", "succeeded", "failed"]
Artifacts = dict[str, JsonValue]

# How a failed attempt was classified: `quota`/`unavailable` paused the queue and didn't use
# up the attempt; `error` is an ordinary failure; `lease_expired` a worker that disappeared.
FailureClassification = Literal["quota", "unavailable", "error", "lease_expired", "requeued"]

# Fixed namespace for job IDs; changing it would re-key every job.
_JOB_NAMESPACE = uuid.UUID("5b0d6f6e-3c1a-4d4e-9a57-0c7b1f3e9a10")


def job_id_for(kind: str, idempotency_key: str) -> uuid.UUID:
    """The deterministic job ID for a (kind, idempotency key) pair."""
    return uuid.uuid5(_JOB_NAMESPACE, json.dumps([kind, idempotency_key]))


class JobFailure(BaseModel):
    model_config = ConfigDict(frozen=True)

    attempt: int
    error: str
    worker: str | None
    at: datetime
    classification: FailureClassification | None = None  # None: recorded before ticket 14


class Job(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    kind: str
    idempotency_key: str
    job_class: JobClass
    payload: dict[str, JsonValue]
    status: JobStatus
    attempts: int
    max_attempts: int
    lease_owner: str | None
    lease_expires_at: datetime | None
    last_error: str | None
    failures: list[JobFailure]
    artifacts: Artifacts
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


@dataclass(frozen=True)
class Enqueued:
    job: Job
    created: bool  # False when a job with the same kind and idempotency key already existed


class QueuePause(BaseModel):
    """The queue-level pause: which kinds are held back, why, and until when."""

    model_config = ConfigDict(frozen=True)

    paused: bool  # the pause is in force now (its backoff hasn't passed)
    level: int  # pauses entered since the last success of a pausable job; 0: clear
    error_class: FailureClass | None  # of the latest pause
    reason: str | None  # the failure that caused the latest pause
    kinds: list[str]  # the job kinds the latest pause holds back
    backoff_seconds: float | None  # the latest pause's backoff
    paused_at: datetime | None
    resume_after: datetime | None
    since: datetime | None  # when this run of pauses began; None once a success clears it
    job_id: uuid.UUID | None  # the job whose failure caused the latest pause
    cleared_at: datetime | None
    pauses_total: int  # every pause ever entered


@dataclass(frozen=True)
class HeldJobs:
    provider: Provider
    kind: str
    job_class: JobClass
    count: int


@dataclass(frozen=True)
class PendingJobs:
    kind: str
    job_class: JobClass
    status: Literal["queued", "running"]
    count: int


def _record_failure(error_sql: str, classification: str) -> str:
    """SET fragment: append a failure for the row's current attempt (UPDATE sees old values)."""
    return (
        "failures = failures || jsonb_build_array(jsonb_build_object("
        f"'attempt', attempts, 'error', {error_sql}, 'worker', lease_owner, 'at', now(), "
        f"'classification', '{classification}')), "
        f"last_error = {error_sql}"
    )


_RECORD_LOST_LEASE = _record_failure(
    "'lease expired (held by ' || lease_owner || ')'", "lease_expired"
)


class JobQueue:
    def __init__(
        self,
        engine: Engine,
        *,
        pacing: Pacing | None = None,
        clock: Clock = utc_now,
        actor: Actor = SYSTEM_ACTOR,
    ) -> None:
        self._engine = engine
        self.pacing = pacing or Pacing()
        self.clock = clock
        self.actor = actor  # who new jobs and pause changes are audited as

    def enqueue(
        self,
        kind: str,
        idempotency_key: str,
        payload: dict[str, JsonValue] | None = None,
        max_attempts: int = 3,
        job_class: JobClass = "interactive",
    ) -> Enqueued:
        """Add a job, or return the existing one for the same kind and idempotency key.

        A `backfill` job is claimed only inside the backfill window (if one is set) and below
        its provider's backfill limit.
        """
        with self._engine.begin() as connection:
            return self.enqueue_within(
                connection, kind, idempotency_key, payload, max_attempts, job_class
            )

    def enqueue_within(
        self,
        connection: Connection,
        kind: str,
        idempotency_key: str,
        payload: dict[str, JsonValue] | None = None,
        max_attempts: int = 3,
        job_class: JobClass = "interactive",
    ) -> Enqueued:
        """`enqueue` within the caller's transaction: the job exists only if it commits."""
        job_id = job_id_for(kind, idempotency_key)
        row = (
            connection.execute(
                text(
                    "INSERT INTO job (id, kind, idempotency_key, job_class, payload,"
                    " max_attempts) VALUES (:id, :kind, :key, :job_class,"
                    " CAST(:payload AS jsonb), :max_attempts) "
                    "ON CONFLICT DO NOTHING RETURNING *"
                ),
                {
                    "id": job_id,
                    "kind": kind,
                    "key": idempotency_key,
                    "job_class": job_class,
                    "payload": json.dumps(payload or {}),
                    "max_attempts": max_attempts,
                },
            )
            .mappings()
            .one_or_none()
        )
        if row is not None:
            record(
                connection,
                self.actor,
                "job.enqueued",
                entity_type="job",
                entity_id=str(job_id),
                new_hash=content_hash(dict(row)),
            )
            return Enqueued(_job(row), created=True)
        existing = _select(connection, job_id)
        assert existing is not None  # the conflicting row exists; jobs are never deleted
        return Enqueued(existing, created=False)

    def get(self, job_id: uuid.UUID) -> Job | None:
        with self._engine.connect() as connection:
            return _select(connection, job_id)

    def claim(self, owner: str, lease: timedelta) -> Job | None:
        """Lease the oldest runnable job to `owner`, or return None if there is none.

        Runnable means queued, or running under an expired lease (its worker is presumed
        dead), and held back neither by the queue pause (its kind is paused), nor by the
        backfill window (a backfill job outside it), nor by its provider's budget (the
        window's usage is at the limit for its class; `atlas.jobs.budget`). Provider usage
        recorded since the last claim is counted first, at the pacing clock's now.
        Reclaiming records the lost attempt as a failure; if that attempt was the last one,
        the job fails instead of running again.
        """
        while True:
            now = self.clock()
            held = self._budget_holds(now)
            with self._engine.begin() as connection:
                candidate = connection.execute(
                    text(
                        "SELECT id, status, attempts, max_attempts FROM job "
                        "WHERE (status = 'queued' "
                        "   OR (status = 'running' AND lease_expires_at <= now())) "
                        "  AND NOT EXISTS (SELECT FROM queue_pause p WHERE p.level > 0"
                        "      AND p.resume_after > :now AND job.kind = ANY(p.kinds)) "
                        "  AND (job.job_class <> 'backfill' OR :window_open) "
                        "  AND job.kind <> ALL(:held_all) "
                        "  AND (job.job_class <> 'backfill' OR job.kind <> ALL(:held_backfill)) "
                        "ORDER BY created_at, id LIMIT 1 "
                        "FOR UPDATE OF job SKIP LOCKED"
                    ),
                    {
                        "now": now,
                        "window_open": self.pacing.window_open(now),
                        "held_all": held.all_classes,
                        "held_backfill": held.backfill,
                    },
                ).one_or_none()
                if candidate is None:
                    return None
                expired = candidate.status == "running"
                if expired and candidate.attempts >= candidate.max_attempts:
                    connection.execute(
                        text(
                            f"UPDATE job SET status = 'failed', {_RECORD_LOST_LEASE}, "  # noqa: S608 (constant fragments)
                            "lease_owner = NULL, lease_expires_at = NULL, "
                            "finished_at = now(), updated_at = now() "
                            "WHERE id = :id"
                        ),
                        {"id": candidate.id},
                    )
                    continue
                lost_attempt = f"{_RECORD_LOST_LEASE}, " if expired else ""
                row = (
                    connection.execute(
                        text(
                            f"UPDATE job SET {lost_attempt}status = 'running', "  # noqa: S608 (constant fragments)
                            "attempts = attempts + 1, lease_owner = :owner, "
                            "lease_expires_at = now() + make_interval(secs => :lease), "
                            "started_at = coalesce(started_at, now()), updated_at = now() "
                            "WHERE id = :id RETURNING *"
                        ),
                        {"id": candidate.id, "owner": owner, "lease": lease.total_seconds()},
                    )
                    .mappings()
                    .one()
                )
                return _job(row)

    def budget_usage(self) -> list[ProviderBudget]:
        """Each provider's rolling window now (empty without budgets); reads only."""
        budgets = self.pacing.budgets
        if budgets is None:
            return []
        with self._engine.connect() as connection:
            return list(window_usage(connection, budgets, self.clock()).values())

    def held_by_budget(self) -> list[HeldJobs]:
        """Queued jobs the budgets hold back now, counted by provider, kind and class."""
        held = holds(self.budget_usage())
        with self._engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT kind, job_class, count(*) AS count FROM job WHERE status = 'queued'"
                    " AND (kind = ANY(:held_all)"
                    "      OR (job_class = 'backfill' AND kind = ANY(:held_backfill)))"
                    " GROUP BY kind, job_class ORDER BY kind, job_class"
                ),
                {"held_all": held.all_classes, "held_backfill": held.backfill},
            ).mappings()
            return [
                HeldJobs(provider=PROVIDER_KINDS[row["kind"]], **row)  # pyright: ignore[reportArgumentType]
                for row in rows
            ]

    def _budget_holds(self, now: datetime) -> Holds:
        """Count new provider usage, then the kinds the budgets hold (none without budgets)."""
        budgets = self.pacing.budgets
        if budgets is None:
            return Holds([], [])
        with self._engine.begin() as connection:
            sweep(connection, now)
            return holds(window_usage(connection, budgets, now).values())

    def complete(self, job: Job, owner: str, artifacts: Artifacts) -> bool:
        """Record success. False if `owner` no longer holds this attempt's lease."""
        return self._finish(
            job,
            owner,
            "status = 'succeeded', artifacts = CAST(:artifacts AS jsonb), finished_at = now()",
            {"artifacts": json.dumps(artifacts)},
        )

    def fail(self, job: Job, owner: str, error: str, *, retry: bool = True) -> bool:
        """Record a failed attempt; requeue it while attempts remain (and `retry` is set).

        False if `owner` no longer holds this attempt's lease.
        """
        return self._finish(
            job,
            owner,
            f"{_record_failure('CAST(:error AS text)', 'error')}, "
            "status = CASE WHEN :retry AND attempts < max_attempts "
            "              THEN 'queued' ELSE 'failed' END, "
            "finished_at = CASE WHEN :retry AND attempts < max_attempts "
            "                   THEN NULL ELSE now() END",
            {"error": error, "retry": retry},
        )

    def requeue(self, job: Job, owner: str, reason: str) -> bool:
        """Put the job back in the queue without using up its attempt and without pausing,
        with the reason recorded (`requeued`). False if `owner` lost the attempt's lease."""
        return self._finish(
            job,
            owner,
            f"{_record_failure('CAST(:error AS text)', 'requeued')}, "
            "status = 'queued', attempts = attempts - 1",
            {"error": reason},
        )

    def pause(
        self,
        job: Job,
        owner: str,
        error: str,
        failure_class: FailureClass,
        kinds: list[str],
    ) -> tuple[QueuePause, bool]:
        """Pause the queue for a quota or outage failure of `job`, and requeue the job.

        If no pause is in force, this enters the next pause level: the backoff doubles per
        level since the last success, up to the cap. A failure while a pause is in force (a
        job that was already running when it began) doesn't lengthen it. Either way the job
        goes back to the queue without using up its attempt, with the failure recorded.
        Returns the pause and whether `owner` still held the job's lease.
        """
        now = self.clock()
        with self._engine.begin() as connection:
            current = (
                connection.execute(
                    text(
                        "SELECT *, level > 0 AND resume_after > :now AS active"
                        " FROM queue_pause WHERE id = 1 FOR UPDATE"
                    ),
                    {"now": now},
                )
                .mappings()
                .one()
            )
            if not current["active"]:
                level = current["level"] + 1
                backoff = self.pacing.backoff(level)
                paused = (
                    connection.execute(
                        text(
                            "UPDATE queue_pause SET level = :level, error_class = :class,"
                            " reason = :reason, kinds = :kinds, backoff_seconds = :backoff,"
                            " paused_at = :now, resume_after = :resume, job_id = :job,"
                            " episode_started_at = coalesce(episode_started_at, :now),"
                            " updated_at = now() WHERE id = 1 RETURNING *"
                        ),
                        {
                            "level": level,
                            "class": failure_class,
                            "reason": error,
                            "kinds": sorted(kinds),
                            "backoff": backoff.total_seconds(),
                            "now": now,
                            "resume": now + backoff,
                            "job": job.id,
                        },
                    )
                    .mappings()
                    .one()
                )
                connection.execute(
                    text(
                        "INSERT INTO queue_pause_event (id, level, error_class, reason, kinds,"
                        " backoff_seconds, paused_at, resume_after, job_id, job_kind)"
                        " VALUES (:id, :level, :error_class, :reason, :kinds,"
                        " :backoff_seconds, :paused_at, :resume_after, :job_id, :job_kind)"
                    ),
                    {
                        "id": uuid.uuid4(),
                        "level": paused["level"],
                        "error_class": paused["error_class"],
                        "reason": paused["reason"],
                        "kinds": paused["kinds"],
                        "backoff_seconds": paused["backoff_seconds"],
                        "paused_at": paused["paused_at"],
                        "resume_after": paused["resume_after"],
                        "job_id": job.id,
                        "job_kind": job.kind,
                    },
                )
                old = {k: v for k, v in current.items() if k != "active"}
                self._audit_pause(connection, "queue.paused", old, dict(paused))
            requeued = self._update_fenced(
                connection,
                job,
                owner,
                f"{_record_failure('CAST(:error AS text)', failure_class)}, "
                "status = 'queued', attempts = attempts - 1",
                {"error": error},
            )
        return self.pause_state(), requeued

    def clear_pause(self) -> bool:
        """A pausable job succeeded: reset the pause level, once the backoff has passed."""
        now = self.clock()
        with self._engine.begin() as connection:
            old = (
                connection.execute(
                    text(
                        "SELECT * FROM queue_pause"
                        " WHERE id = 1 AND level > 0 AND resume_after <= :now FOR UPDATE"
                    ),
                    {"now": now},
                )
                .mappings()
                .one_or_none()
            )
            if old is None:
                return False
            new = (
                connection.execute(
                    text(
                        "UPDATE queue_pause SET level = 0, episode_started_at = NULL,"
                        " cleared_at = :now, updated_at = now() WHERE id = 1 RETURNING *"
                    ),
                    {"now": now},
                )
                .mappings()
                .one()
            )
            self._audit_pause(connection, "queue.pause_cleared", dict(old), dict(new))
            return True

    def _audit_pause(
        self, connection: Connection, action: str, old: dict[str, Any], new: dict[str, Any]
    ) -> None:
        record(
            connection,
            self.actor,
            action,
            entity_type="queue_pause",
            entity_id="queue",
            old_hash=content_hash(old),
            new_hash=content_hash(new),
        )

    def pause_state(self) -> QueuePause:
        now = self.clock()
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    text(
                        "SELECT level, error_class, reason, kinds, backoff_seconds, paused_at,"
                        " resume_after, episode_started_at AS since, job_id, cleared_at,"
                        " level > 0 AND resume_after > :now AS paused,"
                        " (SELECT count(*) FROM queue_pause_event) AS pauses_total"
                        " FROM queue_pause WHERE id = 1"
                    ),
                    {"now": now},
                )
                .mappings()
                .one()
            )
        return QueuePause.model_validate(dict(row))

    def pending(self) -> list[PendingJobs]:
        """Unfinished jobs, counted by kind, class and status (queued or running)."""
        with self._engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT kind, job_class, status, count(*) AS count FROM job"
                    " WHERE status IN ('queued', 'running')"
                    " GROUP BY kind, job_class, status ORDER BY kind, job_class, status"
                )
            ).mappings()
            return [PendingJobs(**row) for row in rows]

    def _finish(self, job: Job, owner: str, assignments: str, params: dict[str, Any]) -> bool:
        with self._engine.begin() as connection:
            return self._update_fenced(connection, job, owner, assignments, params)

    def _update_fenced(
        self,
        connection: Connection,
        job: Job,
        owner: str,
        assignments: str,
        params: dict[str, Any],
    ) -> bool:
        # Fenced on (owner, attempt): a worker whose lease was reclaimed cannot overwrite
        # the outcome of a later attempt.
        result = connection.execute(
            text(
                f"UPDATE job SET {assignments}, lease_owner = NULL, "  # noqa: S608 (constant fragments)
                "lease_expires_at = NULL, updated_at = now() "
                "WHERE id = :id AND status = 'running' "
                "  AND lease_owner = :owner AND attempts = :attempt"
            ),
            {"id": job.id, "owner": owner, "attempt": job.attempts, **params},
        )
        return result.rowcount == 1


def _select(connection: Connection, job_id: uuid.UUID) -> Job | None:
    row = (
        connection.execute(text("SELECT * FROM job WHERE id = :id"), {"id": job_id})
        .mappings()
        .one_or_none()
    )
    return None if row is None else _job(row)


def _job(row: Any) -> Job:
    return Job.model_validate(dict(row))
