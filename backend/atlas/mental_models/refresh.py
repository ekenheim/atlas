"""Refreshing the bank template's mental models: a daily, rate-limited job (spec Part B story 28).

- **The schedule.** Once a day, from `ATLAS_MENTAL_MODEL_REFRESH_AT` (UTC) on, the worker
  enqueues one `refresh_mental_model` job per template mental model, keyed by the model and
  the day, so a day never gets a second scheduled refresh however often the worker polls or
  restarts, and missed days aren't caught up. Nothing is scheduled until a template has been
  applied to the bank.
- **The job** is pausable: a quota or outage failure pauses the queue like a retain's, and
  a paused queue doesn't claim it. It never refreshes a model inside the model's
  `min_refresh_interval_seconds` (from the template) since its last refresh, whether Atlas
  asked for that one or it was made in Hindsight itself; and it doesn't refresh a
  model Hindsight reports as not stale (nothing new in its scope). Otherwise it asks
  Hindsight to refresh the model, polls the operation, and records the new content.
- **Every decision is recorded** as a `mental_model_refresh` row (skipped, submitted,
  completed or failed), with the model's content and raw citations. A completed refresh is
  audited (`mental_model.refreshed`).
- **A submitted refresh is a run** (spec Part B stories 15 and 32): when LiteLLM and Hindsight
  are both configured, it starts a `run` (code, Hindsight and template versions, the routed
  model behind each alias) before asking Hindsight, and finishes it when the operation ends.
  Hindsight's refresh operation reports no token usage, so its totals stay 0.

Atlas's job is the only scheduler (memory-quality ticket 10): the template gives Hindsight
no `refresh_cron` and never refreshes after consolidation, so every automatic refresh is one
Atlas submitted, counted in the `codex` budget (`atlas.jobs.budget`). A refresh made in
Hindsight itself (its API or UI) is still found: each record says who made the refresh it
records (`refreshed_by`: `atlas`, or `hindsight` for one Atlas didn't make). A manual
refresh request is never rate-limited by Hindsight, which is why Atlas enforces the interval
itself.
"""

import hashlib
import json
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection, Engine, RowMapping, text

from atlas.audit import Actor, record
from atlas.bank_template import BankTemplate, TemplateMentalModel, applied_template_version
from atlas.hindsight import HindsightGateway, MentalModel, OperationTimeout
from atlas.jobs.pacing import Clock, TransientFailure, classify_failure, utc_now
from atlas.jobs.queue import Artifacts, Enqueued, Job, JobQueue
from atlas.retention.service import operation_error_class
from atlas.runs import RunNotFound, RunRecorder

REFRESH_KIND = "refresh_mental_model"

type RefreshStatus = Literal["skipped", "submitted", "completed", "failed"]
type SkipReason = Literal["min_interval", "not_stale"]
type RefreshedBy = Literal["atlas", "hindsight"]


class UnknownMentalModel(LookupError):
    """The job names a mental model the bank template doesn't define."""


class RefreshPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mental_model_id: str = Field(min_length=1)
    scheduled_for: date | None = None  # the day a scheduled refresh is for; None: by hand


def refresh_key(bank_id: str, mental_model_id: str, day: date) -> str:
    """The idempotency key of a day's scheduled refresh of one model."""
    return f"{REFRESH_KIND}:{bank_id}:{mental_model_id}:{day.isoformat()}"


@dataclass(frozen=True)
class RefreshTimings:
    poll_timeout: float = 240.0  # below the job lease; a timed-out poll is retried
    poll_interval: float = 5.0


class RefreshSchedule:
    """Enqueues each template mental model's refresh once a day, at `at` (UTC) or later."""

    def __init__(self, engine: Engine, bank_id: str, template: BankTemplate, at: time) -> None:
        self._engine = engine
        self._bank_id = bank_id
        self._template = template
        self._at = at
        self._scheduled: date | None = None

    def __call__(self, now: datetime) -> list[Enqueued]:
        moment = now.astimezone(UTC)
        day = moment.date()
        if self._scheduled == day or moment.time() < self._at:
            return []
        with self._engine.connect() as connection:
            if applied_template_version(connection, self._bank_id) is None:
                return []
        queue = JobQueue(self._engine)  # audited as the system actor's: Atlas schedules it
        enqueued = [
            queue.enqueue(
                REFRESH_KIND,
                refresh_key(self._bank_id, model.id, day),
                RefreshPayload(mental_model_id=model.id, scheduled_for=day).model_dump(mode="json"),
            )
            for model in self._template.mental_models
        ]
        self._scheduled = day
        return enqueued


class MentalModelRefresher:
    """The `refresh_mental_model` job for one bank."""

    def __init__(
        self,
        engine: Engine,
        gateway: HindsightGateway,
        template: BankTemplate,
        actor: Actor,
        *,
        clock: Clock = utc_now,
        timings: RefreshTimings | None = None,
        runs: RunRecorder | None = None,
    ) -> None:
        self._runs = runs
        self._engine = engine
        self._gateway = gateway
        self._template = template
        self._actor = actor
        self._clock = clock
        self._timings = timings or RefreshTimings()

    @property
    def bank_id(self) -> str:
        return self._gateway.bank_id

    def refresh(self, payload: RefreshPayload, job: Job) -> Artifacts:
        definition = self._template.mental_model(payload.mental_model_id)
        if definition is None:
            raise UnknownMentalModel(
                f"the bank template defines no mental model {payload.mental_model_id!r}"
            )
        base: Artifacts = {"mental_model_id": definition.id}
        latest = self._latest_for_job(job.id)
        try:
            if latest is not None and latest["status"] == "submitted":
                return base | self._await(latest)  # an earlier attempt submitted it
            if latest is not None and (
                latest["status"] in ("skipped", "completed") or latest["error_class"] == "permanent"
            ):
                return base | {
                    "outcome": f"already_{latest['status']}",
                    "refresh_id": str(latest["id"]),
                }
            # First attempt, or the last refresh failed for quota or availability (the
            # pause has lifted): decide afresh.
            return base | self._decide(definition, payload, job)
        except Exception as error:
            if job.attempts >= job.max_attempts and classify_failure(error) is None:
                self._fail_submitted(job.id, f"{type(error).__name__}: {error}")
            raise

    # --- deciding ------------------------------------------------------------------------------

    def _decide(
        self, definition: TemplateMentalModel, payload: RefreshPayload, job: Job
    ) -> Artifacts:
        now = self._clock()
        model = self._gateway.get_mental_model(definition.id)
        interval = timedelta(seconds=definition.trigger.min_refresh_interval_seconds)
        last = self._last_refresh(definition.id, model)
        fields: dict[str, object] = {
            "mental_model_id": definition.id,
            "job_id": job.id,
            "scheduled_for": payload.scheduled_for,
            "min_interval": definition.trigger.min_refresh_interval_seconds,
            "previous_refreshed_at": model.last_refreshed_at,
            "requested_at": now,
        }
        reason: SkipReason | None = None
        if last is not None and now - last < interval:
            reason = "min_interval"
        elif model.is_stale is False:
            reason = "not_stale"
        if reason is not None:
            row = self._insert(
                fields
                | {
                    "status": "skipped",
                    "skip_reason": reason,
                    "operation_id": None,
                    "run_id": None,
                    **_refresh_record(model),
                    "completed_at": now,
                    "refreshed_by": self._refreshed_by(definition.id, model),
                }
            )
            outcome: Artifacts = {
                "outcome": "skipped",
                "reason": reason,
                "refresh_id": str(row["id"]),
            }
            if last is not None:
                outcome["last_refreshed_at"] = last.isoformat()
            return outcome
        run = self._runs.start(REFRESH_KIND) if self._runs is not None else None
        try:
            submitted = self._gateway.refresh_mental_model(definition.id)
        except Exception:
            self._finish_run(run.id if run is not None else None)
            raise
        row = self._insert(
            fields
            | {
                "status": "submitted",
                "skip_reason": None,
                "operation_id": submitted.operation_id,
                "run_id": run.id if run is not None else None,
                "content": None,
                "content_sha256": None,
                "raw_citations": "[]",
                "refreshed_at": None,
                "completed_at": None,
                "refreshed_by": None,
            }
        )
        return self._await(row)

    def _last_refresh(self, mental_model_id: str, model: MentalModel) -> datetime | None:
        """When the model was last refreshed, by Atlas or by Hindsight on its own."""
        with self._engine.connect() as connection:
            requested = connection.execute(
                text(
                    "SELECT max(requested_at) FROM mental_model_refresh"
                    " WHERE bank_id = :bank AND mental_model_id = :model"
                    " AND status IN ('submitted', 'completed')"
                ),
                {"bank": self.bank_id, "model": mental_model_id},
            ).scalar_one()
        moments = [m for m in (requested, model.last_refreshed_at) if m is not None]
        return max(moments) if moments else None

    def _refreshed_by(self, mental_model_id: str, model: MentalModel) -> RefreshedBy | None:
        """Who made the model's current refresh: Atlas's job (a refresh it completed left
        this `last_refreshed_at`), Hindsight without Atlas, or nobody yet (None)."""
        if model.last_refreshed_at is None:
            return None
        with self._engine.connect() as connection:
            atlas = connection.execute(
                text(
                    "SELECT EXISTS (SELECT FROM mental_model_refresh WHERE bank_id = :bank"
                    " AND mental_model_id = :model AND status = 'completed'"
                    " AND refreshed_at = :refreshed_at)"
                ),
                {
                    "bank": self.bank_id,
                    "model": mental_model_id,
                    "refreshed_at": model.last_refreshed_at,
                },
            ).scalar_one()
        return "atlas" if atlas else "hindsight"

    # --- awaiting the operation ----------------------------------------------------------------

    def _await(self, row: RowMapping) -> Artifacts:
        operation_id: str = row["operation_id"]
        base: Artifacts = {"refresh_id": str(row["id"]), "operation_id": operation_id}
        try:
            operation = self._gateway.wait_for_operation(
                operation_id,
                timeout=self._timings.poll_timeout,
                poll_interval=self._timings.poll_interval,
            )
        except OperationTimeout as error:
            self._update(row["id"], "operation_status = :status", {"status": error.last_status})
            raise
        now = self._clock()
        self._finish_run(row["run_id"])
        if not operation.succeeded:
            error = operation.error_message or (
                f"Hindsight reported the refresh {operation.status} with no error message"
            )
            error_class = operation_error_class(operation)
            self._update(
                row["id"],
                "status = 'failed', operation_status = :status, error = :error,"
                " error_class = :class, result_metadata = CAST(:metadata AS jsonb),"
                " completed_at = :now",
                {
                    "status": operation.status,
                    "error": error,
                    "class": error_class,
                    "metadata": json.dumps(operation.result_metadata),
                    "now": now,
                },
            )
            if error_class != "permanent":
                raise TransientFailure(
                    error_class,
                    f"Hindsight refresh {operation_id} of {row['mental_model_id']}"
                    f" {operation.status} ({error_class}): {error}",
                )
            return base | {"outcome": "failed", "error": error}
        model = self._gateway.get_mental_model(row["mental_model_id"])
        recorded = _refresh_record(model)
        with self._engine.begin() as connection:
            previous = connection.execute(
                text(
                    "SELECT content_sha256 FROM mental_model_refresh"
                    " WHERE bank_id = :bank AND mental_model_id = :model"
                    " AND status = 'completed' ORDER BY completed_at DESC, id LIMIT 1"
                ),
                {"bank": self.bank_id, "model": row["mental_model_id"]},
            ).scalar_one_or_none()
            self._update(
                row["id"],
                "status = 'completed', operation_status = :status, refreshed_by = 'atlas',"
                " result_metadata = CAST(:metadata AS jsonb), refreshed_at = :refreshed_at,"
                " content = :content, content_sha256 = :content_sha256,"
                " raw_citations = CAST(:raw_citations AS jsonb), completed_at = :now",
                {
                    "status": operation.status,
                    "metadata": json.dumps(operation.result_metadata),
                    "now": now,
                    **recorded,
                },
                connection=connection,
            )
            record(
                connection,
                self._actor,
                "mental_model.refreshed",
                entity_type="mental_model",
                entity_id=f"{self.bank_id}:{row['mental_model_id']}",
                old_hash=previous,
                new_hash=str(recorded["content_sha256"]),
            )
        return base | {
            "outcome": "completed",
            "refreshed_at": model.last_refreshed_at.isoformat()
            if model.last_refreshed_at
            else None,
        }

    def _fail_submitted(self, job_id: uuid.UUID, error: str) -> None:
        latest = self._latest_for_job(job_id)
        if latest is not None and latest["status"] == "submitted":
            self._finish_run(latest["run_id"])
            self._update(
                latest["id"],
                "status = 'failed', error = :error, error_class = 'permanent', completed_at = :now",
                {"error": error[:2000], "now": self._clock()},
            )

    def _finish_run(self, run_id: uuid.UUID | None) -> None:
        """Finish the refresh's run, once (a resumed attempt may find it finished)."""
        if self._runs is None or run_id is None:
            return
        try:
            self._runs.finish(run_id, tokens_in=0, tokens_out=0)
        except RunNotFound:
            pass

    # --- rows ----------------------------------------------------------------------------------

    def _latest_for_job(self, job_id: uuid.UUID) -> RowMapping | None:
        with self._engine.connect() as connection:
            return (
                connection.execute(
                    text(
                        "SELECT * FROM mental_model_refresh WHERE job_id = :job"
                        " ORDER BY requested_at DESC, updated_at DESC LIMIT 1"
                    ),
                    {"job": job_id},
                )
                .mappings()
                .one_or_none()
            )

    def _insert(self, fields: dict[str, object]) -> RowMapping:
        with self._engine.begin() as connection:
            version = applied_template_version(connection, self.bank_id)
            return (
                connection.execute(
                    text(
                        "INSERT INTO mental_model_refresh (id, bank_id, mental_model_id, job_id,"
                        " scheduled_for, template_version, min_refresh_interval_seconds, status,"
                        " skip_reason, operation_id, run_id, previous_refreshed_at, refreshed_at,"
                        " content, content_sha256, raw_citations, requested_at, completed_at,"
                        " refreshed_by)"
                        " VALUES (:id, :bank, :mental_model_id, :job_id, :scheduled_for,"
                        " :version, :min_interval, :status, :skip_reason, :operation_id, :run_id,"
                        " :previous_refreshed_at, :refreshed_at, :content, :content_sha256,"
                        " CAST(:raw_citations AS jsonb), :requested_at, :completed_at,"
                        " :refreshed_by)"
                        " RETURNING *"
                    ),
                    {"id": uuid.uuid4(), "bank": self.bank_id, "version": version, **fields},
                )
                .mappings()
                .one()
            )

    def _update(
        self,
        refresh_id: uuid.UUID,
        assignments: str,
        params: dict[str, object],
        *,
        connection: Connection | None = None,
    ) -> None:
        statement = text(
            f"UPDATE mental_model_refresh SET {assignments}, updated_at = now()"  # noqa: S608 (constant fragments)
            " WHERE id = :id AND status = 'submitted'"
        )
        if connection is not None:
            connection.execute(statement, {"id": refresh_id, **params})
            return
        with self._engine.begin() as own:
            own.execute(statement, {"id": refresh_id, **params})


def _refresh_record(model: MentalModel) -> dict[str, object]:
    """The model's content and raw citations as Hindsight returned them."""
    content = model.content or ""
    raw: Sequence[object] = [memory.model_dump(mode="json") for memory in model.based_on]
    return {
        "content": content,
        "content_sha256": hashlib.sha256(content.encode()).hexdigest(),
        "raw_citations": json.dumps(raw),
        "refreshed_at": model.last_refreshed_at,
    }
