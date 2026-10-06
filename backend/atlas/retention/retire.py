"""Memory holds the intake window (pilot-review ticket 23; `docs/decisions.md`, "Memory holds
the intake window"; `docs/runbooks.md`, "Retiring pre-window sections").

Intake is a rolling window (`ATLAS_INGEST_LOOKBACK_DAYS`); the research bank holds what intake
holds. A company whose first ingest ran before the lookback existed holds older sections too,
and memory sends an Investigator to them. `atlas memory retire --before <date>` takes those
sections out of Memory, modelled on the backfill's delete path (`atlas.retention.backfill`).

- **The job.** `memory_retire` (backfill class; pausable like the backfill, a Hindsight outage
  holds it; it calls no LLM) is one company's. It takes at most `max_sections` of the company's
  sections whose Source Version became available (effective `available_at`) before the bound,
  newest first, in any state but `linked` (a linked version has no document of its own: its
  sections read through the version it links to). A `pending` section with a retain of its
  Source Version in flight is left for the next run.
- **Each section.** `DELETE .../documents/{id}` (a document Hindsight no longer has is no
  error), then in one transaction the section's state is `retired` and a `memory_retirement`
  row records the memories the document held, the state and profile it had, the run, the bound,
  the job, and what Hindsight answered (`memory_units_deleted`; `document_deleted` false for an
  absent document). The Source Version stays in the ledger and the archive, citable.
- **Nothing takes it back.** A retired section is in none of the retain, retry, backfill (stuck
  rule included) or triage paths; a later Source Version of the same document is a new
  version and is retained as usual.
- **Done.** The job records the bank's `pending_consolidation` before and after and ends by
  enqueueing a `consolidate` (backfill class, under the round budget): an observation that
  cited a deleted fact is invalidated and rebuilt from its surviving facts only by a
  consolidation.
- **A run is bounded and resumes**: `--max-sections` caps the sections taken (counted by the
  run's `memory_retirement` rows, so a retry does not take more); a rerun takes the next ones,
  because those taken are no longer candidates.
"""

import json
import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field, JsonValue
from sqlalchemy import Connection, Engine, RowMapping, text

from atlas.audit import Actor, content_hash, record
from atlas.hindsight import HindsightGateway, HindsightNotFound
from atlas.jobs.queue import Artifacts, Job, JobQueue
from atlas.retention.backfill import IN_FLIGHT
from atlas.retention.consolidation import enqueue_consolidation

RETIRE_KIND = "memory_retire"
# The states a retirement takes (`linked` has no document; `retired` is already done).
RETIRABLE_STATES = ("pending", "completed", "zero_fact", "failed", "cancelled")


class RetirePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company_id: uuid.UUID
    run: str = Field(min_length=1)
    before: datetime
    max_sections: int | None = Field(default=None, ge=1)


_FROM = (
    " FROM memory_document m"
    " JOIN source_version v ON v.id = m.source_version_id"
    # The corrected availability, bounded here so the bound reads the view (the as-of check
    # of tests/unit/test_availability_readers.py reads one constant at a time).
    " JOIN source_version_availability a ON a.source_version_id = v.id"
    "  AND a.available_at < :before"
    " JOIN source_document d ON d.id = v.source_document_id"
)
_WHERE = (
    " WHERE m.bank_id = :bank AND d.company_id = :company"
    " AND m.hindsight_document_id IS NOT NULL AND m.retain_state = ANY(:states)"
    f" AND NOT (m.retain_state = 'pending' AND {IN_FLIGHT})"
)


def _params(bank_id: str, company_id: uuid.UUID, before: datetime) -> dict[str, Any]:
    return {
        "bank": bank_id,
        "company": company_id,
        "before": before,
        "states": list(RETIRABLE_STATES),
    }


def candidates(
    connection: Connection,
    bank_id: str,
    company_id: uuid.UUID,
    before: datetime,
    limit: int | None = None,
) -> list[RowMapping]:
    """The company's sections a retirement takes now, newest documents first."""
    return list(
        connection.execute(
            text(
                "SELECT m.id, m.hindsight_document_id, m.retain_state, m.retain_profile,"
                " m.memory_ids, m.updated_at"
                f"{_FROM}{_WHERE}"
                " ORDER BY a.available_at DESC, m.source_version_id, m.char_start, m.id"
                " LIMIT :limit"
            ),
            {**_params(bank_id, company_id, before), "limit": limit},
        ).mappings()
    )


def remaining(connection: Connection, bank_id: str, company_id: uuid.UUID, before: datetime) -> int:
    """How many of the company's sections a retirement would take now."""
    return int(
        connection.execute(
            text(f"SELECT count(*){_FROM}{_WHERE}"),
            _params(bank_id, company_id, before),
        ).scalar_one()
    )


def enqueue_retirements(
    engine: Engine,
    queue: JobQueue,
    bank_id: str,
    company_ids: Sequence[uuid.UUID],
    *,
    before: datetime,
    max_sections: int | None,
    run: str,
) -> list[dict[str, Any]]:
    """Enqueue one retirement job per company with sections to take, in the order given.
    `max_sections` bounds the whole run: each company is allotted what is left of it. With
    `max_sections` 0 nothing is enqueued: the plan only counts. Returns each company's plan."""
    plan: list[dict[str, Any]] = []
    with engine.connect() as connection:
        budget = max_sections
        for company_id in company_ids:
            left = remaining(connection, bank_id, company_id, before)
            allotted = left if budget is None else min(left, budget)
            if budget is not None:
                budget -= allotted
            plan.append(
                {
                    "company_id": str(company_id),
                    "sections_before_window": left,
                    "allotted": allotted,
                    "job": None,
                }
            )
    if max_sections == 0:
        return plan
    for entry in plan:
        if entry["allotted"] == 0:
            continue
        enqueued = queue.enqueue(
            RETIRE_KIND,
            f"{RETIRE_KIND}:{run}:{entry['company_id']}",
            RetirePayload(
                company_id=uuid.UUID(entry["company_id"]),
                run=run,
                before=before,
                max_sections=None if max_sections is None else entry["allotted"],
            ).model_dump(mode="json"),
            job_class="backfill",
        )
        entry["job"] = str(enqueued.job.id)
    return plan


class Retire:
    """The `memory_retire` job."""

    def __init__(self, engine: Engine, gateway: HindsightGateway, actor: Actor) -> None:
        self._engine = engine
        self._gateway = gateway
        self._actor = actor
        self._queue = JobQueue(engine, actor=actor)

    @property
    def bank_id(self) -> str:
        return self._gateway.bank_id

    def run(self, payload: RetirePayload, job: Job) -> Artifacts:
        before_pending = self._gateway.bank_stats().pending_consolidation
        with self._engine.connect() as connection:
            already = int(
                connection.execute(
                    text(
                        "SELECT count(*) FROM memory_retirement r"
                        " JOIN memory_document m ON m.id = r.memory_document_id"
                        " JOIN source_version v ON v.id = m.source_version_id"
                        " JOIN source_document d ON d.id = v.source_document_id"
                        " WHERE r.run_key = :run AND d.company_id = :company"
                    ),
                    {"run": payload.run, "company": payload.company_id},
                ).scalar_one()
            )
            limit = None if payload.max_sections is None else max(payload.max_sections - already, 0)
            rows = (
                []
                if limit == 0
                else candidates(connection, self.bank_id, payload.company_id, payload.before, limit)
            )
        retired = 0
        absent = 0
        units = 0
        by_state: dict[str, int] = {}
        for section in rows:
            try:
                deleted = self._gateway.delete_document(section["hindsight_document_id"])
                memory_units: int | None = deleted.memory_units_deleted
                present = True
            except HindsightNotFound:
                memory_units, present = None, False
                absent += 1
            with self._engine.begin() as connection:
                if self._retire(connection, section, payload, job, present, memory_units):
                    retired += 1
                    units += memory_units or 0
                    state = section["retain_state"]
                    by_state[state] = by_state.get(state, 0) + 1
        with self._engine.connect() as connection:
            left = remaining(connection, self.bank_id, payload.company_id, payload.before)
        after_pending = self._gateway.bank_stats().pending_consolidation
        consolidation = enqueue_consolidation(
            self._queue,
            f"consolidate:retire:{payload.run}:{payload.company_id}",
            job_class="backfill",
        )
        result: dict[str, JsonValue] = {
            "bank_id": self.bank_id,
            "company_id": str(payload.company_id),
            "run": payload.run,
            "before": payload.before.isoformat(),
            "sections_retired": retired,
            "retired_by_state": dict(sorted(by_state.items())),
            "documents_absent": absent,
            "memory_units_deleted": units,
            "sections_left": left,
            "pending_consolidation_before": before_pending,
            "pending_consolidation_after": after_pending,
            "consolidate_job": str(consolidation.job.id),
        }
        return result

    def _retire(
        self,
        connection: Connection,
        section: RowMapping,
        payload: RetirePayload,
        job: Job,
        present: bool,
        memory_units: int | None,
    ) -> bool:
        """The section is `retired`, its memories recorded, in one transaction."""
        unchanged = " AND updated_at = :updated" if section["retain_state"] == "pending" else ""
        old = (
            connection.execute(
                text(
                    "SELECT * FROM memory_document WHERE id = :id"  # noqa: S608
                    f" AND retain_state = :state{unchanged} FOR UPDATE"
                ),
                {
                    "id": section["id"],
                    "state": section["retain_state"],
                    "updated": section["updated_at"],
                },
            )
            .mappings()
            .one_or_none()
        )
        if old is None:
            return False  # changed since it was chosen: left as it is
        recorded: Any = old["memory_ids"]
        memory_ids = cast(list[str], recorded) if isinstance(recorded, list) else []
        connection.execute(
            text(
                "INSERT INTO memory_retirement (id, memory_document_id, bank_id,"
                " hindsight_document_id, run_key, before_date, job_id, from_state,"
                " from_profile, retired_memory_ids, document_deleted, memory_units_deleted)"
                " VALUES (:id, :document, :bank, :hindsight, :run, :before, :job, :state,"
                " :profile, CAST(:memories AS jsonb), :present, :units)"
            ),
            {
                "id": uuid.uuid4(),
                "document": old["id"],
                "bank": self.bank_id,
                "hindsight": old["hindsight_document_id"],
                "run": payload.run,
                "before": payload.before,
                "job": job.id,
                "state": old["retain_state"],
                "profile": old["retain_profile"],
                "memories": json.dumps(memory_ids),
                "present": present,
                "units": memory_units,
            },
        )
        new = (
            connection.execute(
                text(
                    "UPDATE memory_document SET retain_state = 'retired', error = NULL,"
                    " error_class = NULL, transient_retries = 0, fact_count = NULL,"
                    " memory_ids = NULL, extraction_errors = NULL, updated_at = now()"
                    " WHERE id = :id RETURNING *"
                ),
                {"id": old["id"]},
            )
            .mappings()
            .one()
        )
        record(
            connection,
            self._actor,
            "memory_document.retired",
            entity_type="memory_document",
            entity_id=str(old["id"]),
            old_hash=content_hash(dict(old)),
            new_hash=content_hash(dict(new)),
        )
        return True
