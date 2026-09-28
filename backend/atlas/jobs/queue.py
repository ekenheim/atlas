"""The Postgres job table as a work queue: idempotent enqueue, leased claims, bounded retries.

All clocks are the database's (`now()`), so lease expiry means the same thing to every worker.
"""

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, JsonValue
from sqlalchemy import Connection, Engine, text

JobStatus = Literal["queued", "running", "succeeded", "failed"]
Artifacts = dict[str, JsonValue]

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


class Job(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    kind: str
    idempotency_key: str
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


def _record_failure(error_sql: str) -> str:
    """SET fragment: append a failure for the row's current attempt (UPDATE sees old values)."""
    return (
        "failures = failures || jsonb_build_array(jsonb_build_object("
        f"'attempt', attempts, 'error', {error_sql}, 'worker', lease_owner, 'at', now())), "
        f"last_error = {error_sql}"
    )


_RECORD_LOST_LEASE = _record_failure("'lease expired (held by ' || lease_owner || ')'")


class JobQueue:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def enqueue(
        self,
        kind: str,
        idempotency_key: str,
        payload: dict[str, JsonValue] | None = None,
        max_attempts: int = 3,
    ) -> Enqueued:
        """Add a job, or return the existing one for the same kind and idempotency key."""
        job_id = job_id_for(kind, idempotency_key)
        with self._engine.begin() as connection:
            row = (
                connection.execute(
                    text(
                        "INSERT INTO job (id, kind, idempotency_key, payload, max_attempts) "
                        "VALUES (:id, :kind, :key, CAST(:payload AS jsonb), :max_attempts) "
                        "ON CONFLICT DO NOTHING RETURNING *"
                    ),
                    {
                        "id": job_id,
                        "kind": kind,
                        "key": idempotency_key,
                        "payload": json.dumps(payload or {}),
                        "max_attempts": max_attempts,
                    },
                )
                .mappings()
                .one_or_none()
            )
            if row is not None:
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
        dead). Reclaiming records the lost attempt as a failure; if that attempt was the
        last one, the job fails instead of running again.
        """
        while True:
            with self._engine.begin() as connection:
                candidate = connection.execute(
                    text(
                        "SELECT id, status, attempts, max_attempts FROM job "
                        "WHERE status = 'queued' "
                        "   OR (status = 'running' AND lease_expires_at <= now()) "
                        "ORDER BY created_at, id LIMIT 1 "
                        "FOR UPDATE SKIP LOCKED"
                    )
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
            f"{_record_failure('CAST(:error AS text)')}, "
            "status = CASE WHEN :retry AND attempts < max_attempts "
            "              THEN 'queued' ELSE 'failed' END, "
            "finished_at = CASE WHEN :retry AND attempts < max_attempts "
            "                   THEN NULL ELSE now() END",
            {"error": error, "retry": retry},
        )

    def _finish(self, job: Job, owner: str, assignments: str, params: dict[str, Any]) -> bool:
        # Fenced on (owner, attempt): a worker whose lease was reclaimed cannot overwrite
        # the outcome of a later attempt.
        with self._engine.begin() as connection:
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
