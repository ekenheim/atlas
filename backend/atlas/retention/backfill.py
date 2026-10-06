"""The corpus already in Memory, brought to the current standard (memory-quality ticket 12;
`docs/decisions.md`, "A backfill replaces a section's document"; `docs/runbooks.md`, "Memory
backfill").

What a retained section says (its context, entities, scopes and labels) is versioned by
`RETAIN_PROFILE`; every section retained before the current profile, and every failed or
cancelled one, is brought to it without fetching or parsing anything again. Hindsight takes a
new profile for a stored document in one way: the document is deleted and retained again under
the same ID. A retain of unchanged content under the same ID extracts nothing, and `reprocess`
replays the stored parameters, old context included (ticket 01); a delete then removes the
document's facts and the observations built only from them, and the second retain extracts
again with the new context, tags and entities, giving the facts new IDs (recorded 0.10.2:
`spikes/hindsight/recordings/delete_and_retain/`, 4 LLM requests for the whole sequence).

- **The job.** `memory_backfill` (backfill class, pausable; no LLM of its own) is one company's.
  Its first step takes at most `max_sections` of the company's sections still to bring up:
  those in state `failed` or `cancelled`, and those **stuck** `pending` under an older profile
  (ticket 21: not updated for `ATLAS_BACKFILL_STUCK_AFTER_HOURS` and no retain, poll or
  reprocess job of their Source Version queued or running; Hindsight may hold their document
  under the old profile, and a plain retain of unchanged content would extract nothing), then
  call transcripts, then the rest, newest documents first. For each it deletes the Hindsight
  document (a document Hindsight no longer has is no error), then in one transaction resets
  the section to `pending`, records a `memory_replacement` row (the memories the deleted
  document held, so a citation of one reads as replaced, not broken) and enqueues a
  backfill-class `retain` for its Source Version, which submits the pending sections through
  the existing retain path, under the retain budget and the backfill window, never using the
  interactive reserve. Sections triage skipped are not
  in `memory_document` and stay skipped; a section retained on demand is one like any other.
  A permanently failed section a backfill already took is not taken again.
- **Versions never retained** (pilot-review ticket 22; `atlas.retention.coverage`). Besides
  the sections it takes the company's **gap** versions: parsed English Source Versions the
  bank holds nothing of that nothing is retaining, newest first. A `not_submitted` one gets a
  backfill-class `retain` (which triages first when triage is on); a `triage_failed` one its
  triage again, as `atlas triage retry` does (`retry_failed_triage`). They are taken before
  the sections, since a company with versions never offered to Memory is the larger gap;
  `max_sections` bounds both: a gap version counts as the retain-decided sections it has once
  triaged and as one before, and is taken whole, so the last may overshoot. The job's
  artifacts count them (`versions_taken`, `version_retain_jobs`, `version_triage_jobs`,
  `versions_left`).
- **Done.** The job then follows itself with a `finish` step that waits (by enqueueing itself
  behind the retain and poll jobs) until none of the bank's retains is queued or running,
  and asks for a consolidation (`consolidate`, backfill class) when the company's sections
  are done; the consolidation job's own record names the operation. A run that took nothing
  does the same, so a rerun after a run that was cut short ends with the consolidation and
  retains nothing.
- **A run is bounded and resumes.** `--max-sections` caps the sections taken (counted by
  `memory_replacement` rows of the run, so an interrupted run does not take more on its
  retry); a rerun takes the next sections, because those taken are no longer below the
  profile. A quota or outage pauses the job (it is pausable) and its retry takes what is
  left.
- **Order across companies** (`order_companies`): the seed companies of the pilot's
  investigations first, then the others, each group thinnest in Memory first (fewest completed
  sections), so the companies the pilot found thin are brought up before the ones it already
  read well.
"""

import json
import uuid
from collections.abc import Sequence
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field, JsonValue
from sqlalchemy import Connection, Engine, RowMapping, text

from atlas.audit import Actor, content_hash, record
from atlas.hindsight import HindsightGateway, HindsightNotFound
from atlas.jobs.queue import Artifacts, Enqueued, Job, JobQueue
from atlas.retention.consolidation import enqueue_consolidation
from atlas.retention.context import RETAIN_PROFILE
from atlas.retention.coverage import VersionRow, gaps, version_states
from atlas.retention.service import POLL_KIND, REPROCESS_KIND, RETAIN_KIND, retain_payload
from atlas.retention.triage import TriageRetryRefused, retry_failed_triage

BACKFILL_KIND = "memory_backfill"
# Waiting passes of the finish step before a run gives up waiting (it ends `still_retaining`;
# a rerun asks for the consolidation then).
MAX_WAIT_STEPS = 20
# The jobs that retain into the bank: a company's backfill is done when none is left.
RETAIN_JOB_KINDS = (RETAIN_KIND, POLL_KIND, REPROCESS_KIND)


class BackfillPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company_id: uuid.UUID
    run: str = Field(min_length=1)
    max_sections: int | None = Field(default=None, ge=1)
    step: int = Field(default=0, ge=0)  # 0: take the sections; later: wait, then consolidate


# --- what is left to bring up ---------------------------------------------------------------

# A section stuck `pending` under an older profile (ticket 21): its row not updated for
# `:stuck_after` seconds and no retain, poll or reprocess job of its Source Version queued or
# running. Its outcome was never recorded, though Hindsight may hold its document under the old
# profile; with `:profile` (the current one) and `:stuck_after` bound. Also counted by the
# health read (`atlas.retention.health`).
# A retain of the section's Source Version is in flight: a `retain` of it, or a `poll_operation`
# or `reprocess` of one of its operations, queued or running. Also used by the reconciliation
# (`atlas.retention.reconciliation`, ticket 22).
IN_FLIGHT = (
    "EXISTS (SELECT FROM job j WHERE j.status IN ('queued', 'running') AND ("  # noqa: S608
    f"   (j.kind = '{RETAIN_KIND}'"
    "     AND j.payload ->> 'source_version_id' = CAST(m.source_version_id AS text))"
    f"   OR (j.kind IN ('{POLL_KIND}', '{REPROCESS_KIND}')"
    "     AND j.payload ->> 'operation_id' IN (SELECT o.id FROM hindsight_operation o"
    "       WHERE o.source_version_id = m.source_version_id))))"
)
STUCK = (
    "(m.retain_state = 'pending' AND m.retain_profile IS DISTINCT FROM :profile"
    " AND m.updated_at < now() - make_interval(secs => CAST(:stuck_after AS double precision))"
    f" AND NOT {IN_FLIGHT})"
)
_BELOW = (
    "m.hindsight_document_id IS NOT NULL AND ("  # noqa: S608 (constant fragments)
    "(m.retain_state = 'failed' AND NOT (m.error_class = 'permanent' AND EXISTS ("
    "   SELECT FROM memory_replacement r WHERE r.memory_document_id = m.id)))"
    " OR m.retain_state = 'cancelled'"
    " OR (m.retain_state IN ('completed', 'zero_fact')"
    "   AND m.retain_profile IS DISTINCT FROM :profile)"
    f" OR {STUCK})"
)


def stuck_params(stuck_after_hours: float) -> dict[str, Any]:
    """The bound values of `STUCK`."""
    return {"profile": RETAIN_PROFILE, "stuck_after": stuck_after_hours * 3600.0}


_FROM = (
    " FROM memory_document m"
    " JOIN source_version v ON v.id = m.source_version_id"
    " JOIN source_version_availability a ON a.source_version_id = v.id"
    " JOIN source_document d ON d.id = v.source_document_id"
)


def candidates(
    connection: Connection,
    bank_id: str,
    company_id: uuid.UUID,
    limit: int | None = None,
    *,
    stuck_after_hours: float,
) -> list[RowMapping]:
    """The company's sections a backfill takes now, in the order it takes them: failed,
    cancelled and stuck first, then call transcripts, then the rest; newest documents first."""
    return list(
        connection.execute(
            text(
                "SELECT m.id, m.source_version_id, m.hindsight_document_id, m.retain_state,"
                " m.retain_profile, m.memory_ids, m.updated_at"
                f"{_FROM} WHERE m.bank_id = :bank AND d.company_id = :company AND {_BELOW}"
                " ORDER BY (CASE WHEN m.retain_state IN ('failed', 'cancelled', 'pending')"
                "   THEN 0 WHEN d.provider = 'tradingview' THEN 1 ELSE 2 END),"
                " a.available_at DESC, m.source_version_id, m.char_start, m.id"
                " LIMIT :limit"
            ),
            {
                "bank": bank_id,
                "company": company_id,
                "limit": limit,
                **stuck_params(stuck_after_hours),
            },
        ).mappings()
    )


def remaining(
    connection: Connection, bank_id: str, company_id: uuid.UUID, *, stuck_after_hours: float
) -> int:
    """How many of the company's sections a backfill would take now."""
    return int(
        connection.execute(
            text(
                f"SELECT count(*){_FROM} WHERE m.bank_id = :bank AND d.company_id = :company"
                f" AND {_BELOW}"
            ),
            {"bank": bank_id, "company": company_id, **stuck_params(stuck_after_hours)},
        ).scalar_one()
    )


def gap_costs(connection: Connection, rows: Sequence[VersionRow]) -> dict[uuid.UUID, int]:
    """What each gap version counts against `max_sections`: the sections triage decided to
    retain once it has decided (a `not_submitted` version), else one."""
    decided = {
        row["source_version_id"]: int(row["sections"])
        for row in connection.execute(
            text(
                "SELECT t.source_version_id, count(*) AS sections FROM triage_decision t"
                " WHERE t.source_version_id = ANY(:ids) AND t.decision = 'retain'"
                " AND NOT EXISTS (SELECT FROM triage_decision later"
                "   WHERE later.source_version_id = t.source_version_id"
                "   AND later.section_anchor = t.section_anchor AND later.seq > t.seq)"
                " GROUP BY 1"
            ),
            {"ids": [row.source_version_id for row in rows]},
        ).mappings()
    }
    return {
        row.source_version_id: max(decided.get(row.source_version_id, 1), 1)
        if row.state == "not_submitted"
        else 1
        for row in rows
    }


def gap_units(connection: Connection, bank_id: str, company_id: uuid.UUID) -> int:
    """What the company's gap versions count against `max_sections` in all."""
    rows = gaps(version_states(connection, bank_id, company_id))
    return sum(gap_costs(connection, rows).values())


def profile_counts(
    connection: Connection, bank_id: str, company_id: uuid.UUID, *, stuck_after_hours: float
) -> dict[str, JsonValue]:
    """The company's sections at the current profile, below it, failed (and cancelled),
    pending, and stuck (pending under an older profile, not in flight; what the job's artifacts
    and the health read show)."""
    row = (
        connection.execute(
            text(
                "SELECT"  # noqa: S608 (constant fragments)
                " count(*) FILTER (WHERE m.retain_state IN ('completed', 'zero_fact')"
                "   AND m.retain_profile = :profile) AS at_profile,"
                " count(*) FILTER (WHERE m.retain_state IN ('completed', 'zero_fact')"
                "   AND m.retain_profile IS DISTINCT FROM :profile) AS below_profile,"
                " count(*) FILTER (WHERE m.retain_state IN ('failed', 'cancelled')) AS failed,"
                " count(*) FILTER (WHERE m.retain_state = 'pending') AS pending,"
                f" count(*) FILTER (WHERE {STUCK}) AS stuck"
                f"{_FROM} WHERE m.bank_id = :bank AND d.company_id = :company"
            ),
            {"bank": bank_id, "company": company_id, **stuck_params(stuck_after_hours)},
        )
        .mappings()
        .one()
    )
    return {key: int(value) for key, value in row.items()}


def order_companies(
    connection: Connection, bank_id: str, company_ids: Sequence[uuid.UUID]
) -> list[uuid.UUID]:
    """The companies in the order a backfill runs them: the seeds of the pilot's investigations
    first, then the others; each group thinnest in Memory first (fewest completed sections),
    then by ID."""
    rows = connection.execute(
        text(
            "SELECT c.id,"
            " EXISTS (SELECT FROM investigation i WHERE c.id = ANY(i.seed_company_ids)) AS seed,"
            " (SELECT count(*) FROM memory_document m"
            "  JOIN source_version v ON v.id = m.source_version_id"
            "  JOIN source_document d ON d.id = v.source_document_id"
            "  WHERE d.company_id = c.id AND m.bank_id = :bank"
            "  AND m.retain_state = 'completed') AS completed"
            " FROM company c WHERE c.id = ANY(:ids)"
        ),
        {"bank": bank_id, "ids": list(company_ids)},
    ).mappings()
    ordered = sorted(rows, key=lambda r: (not r["seed"], r["completed"], str(r["id"])))
    return [row["id"] for row in ordered]


def enqueue_backfills(
    engine: Engine,
    queue: JobQueue,
    bank_id: str,
    company_ids: Sequence[uuid.UUID],
    *,
    max_sections: int | None,
    run: str,
    stuck_after_hours: float,
    ordered: bool = True,
) -> list[dict[str, Any]]:
    """Enqueue one backfill job per company that has sections to bring up, in order
    (`order_companies`, unless `ordered` is false: the owner's own order). `max_sections`
    bounds the whole run: each company is allotted what is left of it, and a company that gets
    nothing is left for the next run. A company's work is its sections below the profile and
    its gap versions (`gap_units`; `versions_below` in its plan). Returns each company's plan."""
    plan: list[dict[str, Any]] = []
    with engine.connect() as connection:
        companies = (
            order_companies(connection, bank_id, company_ids) if ordered else list(company_ids)
        )
        budget = max_sections
        for company_id in companies:
            versions = gap_units(connection, bank_id, company_id)
            left = versions + remaining(
                connection, bank_id, company_id, stuck_after_hours=stuck_after_hours
            )
            allotted = left if budget is None else min(left, budget)
            if budget is not None:
                budget -= allotted
            plan.append(
                {
                    "company_id": str(company_id),
                    "sections_below": left - versions,
                    "versions_below": versions,
                    "allotted": allotted,
                    "job": None,
                }
            )
    for entry in plan:
        if entry["allotted"] == 0:
            continue
        enqueued: Enqueued = queue.enqueue(
            BACKFILL_KIND,
            f"{BACKFILL_KIND}:{run}:{entry['company_id']}",
            BackfillPayload(
                company_id=uuid.UUID(entry["company_id"]),
                run=run,
                max_sections=None if max_sections is None else entry["allotted"],
            ).model_dump(mode="json"),
            job_class="backfill",
        )
        entry["job"] = str(enqueued.job.id)
    return plan


# --- the job ---------------------------------------------------------------------------------


class Backfill:
    """The `memory_backfill` job."""

    def __init__(
        self,
        engine: Engine,
        gateway: HindsightGateway,
        actor: Actor,
        *,
        stuck_after_hours: float,
    ) -> None:
        self._engine = engine
        self._gateway = gateway
        self._actor = actor
        self._stuck_after_hours = stuck_after_hours
        self._queue = JobQueue(engine, actor=actor)

    @property
    def bank_id(self) -> str:
        return self._gateway.bank_id

    def run(self, payload: BackfillPayload, job: Job) -> Artifacts:
        if payload.step == 0:
            return self._take(payload)
        return self._finish(payload)

    # --- take ----------------------------------------------------------------------------------

    def _take(self, payload: BackfillPayload) -> Artifacts:
        with self._engine.connect() as connection:
            already = int(
                connection.execute(
                    text(
                        "SELECT count(*) FROM memory_replacement r"
                        " JOIN memory_document m ON m.id = r.memory_document_id"
                        " JOIN source_version v ON v.id = m.source_version_id"
                        " JOIN source_document d ON d.id = v.source_document_id"
                        " WHERE r.run_key = :run AND d.company_id = :company"
                    ),
                    {"run": payload.run, "company": payload.company_id},
                ).scalar_one()
            )
            limit = None if payload.max_sections is None else max(payload.max_sections - already, 0)
            stuck_after = self._stuck_after_hours
            # Versions Memory was never given come first; the sections get what is left.
            gap_rows = (
                []
                if limit == 0
                else gaps(version_states(connection, self.bank_id, payload.company_id))
            )
            costs = gap_costs(connection, gap_rows)
            chosen: list[VersionRow] = []
            spent = 0
            for gap in gap_rows:
                if limit is not None and spent >= limit:
                    break
                chosen.append(gap)
                spent += costs[gap.source_version_id]
            if limit is not None:
                limit = max(limit - spent, 0)
            rows = (
                []
                if limit == 0
                else candidates(
                    connection,
                    self.bank_id,
                    payload.company_id,
                    limit,
                    stuck_after_hours=stuck_after,
                )
            )
            before = profile_counts(
                connection, self.bank_id, payload.company_id, stuck_after_hours=stuck_after
            )
        version_retains, version_triages = self._take_versions(chosen, payload.run)
        by_version: dict[uuid.UUID, list[RowMapping]] = {}
        for row in rows:
            by_version.setdefault(row["source_version_id"], []).append(row)
        retain_jobs: list[JsonValue] = []
        deleted = 0
        absent = 0
        for version_id, sections in by_version.items():
            for section in sections:
                try:
                    self._gateway.delete_document(section["hindsight_document_id"])
                    deleted += 1
                except HindsightNotFound:
                    # Hindsight has no such document (a failed or cancelled section, or a
                    # stuck one whose retain stored nothing).
                    absent += 1
            with self._engine.begin() as connection:
                for section in sections:
                    self._reset(connection, section, payload.run)
                enqueued = self._queue.enqueue_within(
                    connection,
                    RETAIN_KIND,
                    f"retain:{version_id}:backfill:{payload.run}",
                    retain_payload(version_id),
                    job_class="backfill",
                )
                retain_jobs.append(str(enqueued.job.id))
        by_state: dict[str, int] = {}
        for row in rows:
            by_state[row["retain_state"]] = by_state.get(row["retain_state"], 0) + 1
        finish = self._follow(payload, step=1)
        with self._engine.connect() as connection:
            after = profile_counts(
                connection, self.bank_id, payload.company_id, stuck_after_hours=stuck_after
            )
            left = remaining(
                connection, self.bank_id, payload.company_id, stuck_after_hours=stuck_after
            ) + gap_units(connection, self.bank_id, payload.company_id)
            versions_left = len(gaps(version_states(connection, self.bank_id, payload.company_id)))
        return {
            "bank_id": self.bank_id,
            "company_id": str(payload.company_id),
            "run": payload.run,
            "step": "take",
            "versions_taken": len(chosen),
            "version_retain_jobs": version_retains,
            "version_triage_jobs": version_triages,
            "versions_left": versions_left,
            "sections_taken": len(rows),
            "taken_by_state": dict(sorted(by_state.items())),
            "documents_deleted": deleted,
            "documents_absent": absent,
            "source_versions": len(by_version),
            "retain_jobs": retain_jobs,
            "sections_left": left,
            "counts_before": before,
            "counts_after": after,
            "next_job": str(finish.job.id),
        }

    def _take_versions(
        self, chosen: Sequence[VersionRow], run: str
    ) -> tuple[list[JsonValue], list[JsonValue]]:
        """Offer the gap versions to Memory: a retain (backfill class) of each `not_submitted`
        one, a new triage (`retry_failed_triage`) of each `triage_failed` one."""
        retains: list[JsonValue] = []
        triages: list[JsonValue] = []
        for gap in chosen:
            if gap.state == "not_submitted":
                enqueued = self._queue.enqueue(
                    RETAIN_KIND,
                    f"retain:{gap.source_version_id}:backfill:{run}",
                    retain_payload(gap.source_version_id),
                    job_class="backfill",
                )
                retains.append(str(enqueued.job.id))
                continue
            try:
                triages.extend(
                    str(job.id)
                    for job in retry_failed_triage(self._engine, self._actor, gap.source_version_id)
                )
            except TriageRetryRefused:
                continue  # its triage was retried since it was listed
        return retains, triages

    def _reset(self, connection: Connection, section: RowMapping, run: str) -> None:
        """The section is `pending` again, its replaced memories recorded, in one transaction."""
        # A stuck section is still the one chosen only if nothing touched it since (a retain
        # submitting it meanwhile would have updated it).
        unchanged = " AND updated_at = :updated" if section["retain_state"] == "pending" else ""
        old = (
            connection.execute(
                text(
                    "SELECT * FROM memory_document WHERE id = :id"  # noqa: S608 (constant fragments)
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
            return  # changed since it was chosen (retried by hand, say): left as it is
        recorded: Any = old["memory_ids"]
        memory_ids = cast(list[str], recorded) if isinstance(recorded, list) else []
        connection.execute(
            text(
                "INSERT INTO memory_replacement (id, memory_document_id, bank_id,"
                " hindsight_document_id, run_key, from_state, from_profile,"
                " replaced_memory_ids) VALUES (:id, :document, :bank, :hindsight, :run, :state,"
                " :profile, CAST(:memories AS jsonb))"
            ),
            {
                "id": uuid.uuid4(),
                "document": old["id"],
                "bank": self.bank_id,
                "hindsight": old["hindsight_document_id"],
                "run": run,
                "state": old["retain_state"],
                "profile": old["retain_profile"],
                "memories": json.dumps(memory_ids),
            },
        )
        new = (
            connection.execute(
                text(
                    "UPDATE memory_document SET retain_state = 'pending', operation_id = NULL,"
                    " error = NULL, error_class = NULL, transient_retries = 0,"
                    " fact_count = NULL, memory_ids = NULL, extraction_errors = NULL,"
                    " updated_at = now() WHERE id = :id RETURNING *"
                ),
                {"id": old["id"]},
            )
            .mappings()
            .one()
        )
        record(
            connection,
            self._actor,
            "memory_document.backfill_reset",
            entity_type="memory_document",
            entity_id=str(old["id"]),
            old_hash=content_hash(dict(old)),
            new_hash=content_hash(dict(new)),
        )

    # --- finish --------------------------------------------------------------------------------

    def _follow(self, payload: BackfillPayload, *, step: int) -> Enqueued:
        return self._queue.enqueue(
            BACKFILL_KIND,
            f"{BACKFILL_KIND}:{payload.run}:{payload.company_id}:{step}",
            payload.model_copy(update={"step": step}).model_dump(mode="json"),
            job_class="backfill",
        )

    def _finish(self, payload: BackfillPayload) -> Artifacts:
        base: Artifacts = {
            "bank_id": self.bank_id,
            "company_id": str(payload.company_id),
            "run": payload.run,
            "step": "finish",
            "wait_step": payload.step,
        }
        with self._engine.connect() as connection:
            retaining = bool(
                connection.execute(
                    text(
                        "SELECT EXISTS (SELECT FROM job WHERE kind = ANY(:kinds)"
                        " AND status IN ('queued', 'running'))"
                    ),
                    {"kinds": list(RETAIN_JOB_KINDS)},
                ).scalar_one()
            )
            stuck_after = self._stuck_after_hours
            counts = profile_counts(
                connection, self.bank_id, payload.company_id, stuck_after_hours=stuck_after
            )
            left = remaining(
                connection, self.bank_id, payload.company_id, stuck_after_hours=stuck_after
            )
        if retaining:
            if payload.step >= MAX_WAIT_STEPS:
                return {**base, "outcome": "still_retaining", "counts": counts}
            following = self._follow(payload, step=payload.step + 1)
            return {
                **base,
                "outcome": "waiting",
                "counts": counts,
                "next_job": str(following.job.id),
            }
        consolidation = enqueue_consolidation(
            self._queue,
            f"consolidate:backfill:{payload.run}:{payload.company_id}",
            job_class="backfill",
        )
        return {
            **base,
            "outcome": "consolidation_requested",
            "consolidate_job": str(consolidation.job.id),
            "counts": counts,
            "sections_left": left,
        }
