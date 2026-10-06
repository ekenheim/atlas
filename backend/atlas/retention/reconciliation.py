"""Atlas's records reconciled with Memory every night (memory-quality ticket 22;
`docs/decisions.md`, "Atlas's records are reconciled with Memory"; `docs/runbooks.md`, "Memory
reconciliation").

Three defects of one day (2026-10-03) were all Atlas's records diverging from Hindsight, each
found by accident. The `reconcile_memory` job compares what Atlas records about the research
bank with what Hindsight holds, read-only (no LLM call, no write to Hindsight), and records
every difference:

1. `section_missing`: a section Atlas records `completed` or `zero_fact` whose Hindsight
   document does not exist (absent from the listing, and a read of it answers 404).
2. `document_unrecorded`: a document of the bank (`srcv:` IDs) whose section Atlas records
   `pending` and **stuck** (ticket 21's rule, `atlas.retention.backfill.STUCK`), or `failed`
   or `cancelled` with no retain of it in flight (`IN_FLIGHT`), or does not know at all (an
   orphan).
3. `profile_mismatch`: a section Atlas records `completed` or `zero_fact` at the current
   `RETAIN_PROFILE` whose document's `retain_params` lack the item's observation scopes (one
   per theme tag the document carries) or the entities Atlas recorded giving it.
4. `observation_scope_outside`: observations in a scope other than one theme's (one
   `theme:<slug>` tag alone); counted in observations, sampled by scope.
5. `config_drift`: a setting the bank template sets (every key of its `manifest.bank`)
   whose live value (`GET .../config`) differs; sampled by setting name. Compared normalised:
   a key absent, null, `{}` or `[]` on either side is equal (the live bank stores the
   template's `entity_labels` groups with `"fields": {}`); object key order never matters.
6. `consolidation_untracked`: a consolidation operation of the bank pending or processing that
   no `submitted` run of Atlas follows (a run follows its requested operation and every one
   created after it, as `atlas.retention.consolidation` counts rounds), or a `submitted` run
   whose last round has ended in Hindsight with no round of it still running.
7. `version_not_in_memory` (pilot-review ticket 22; `atlas.retention.coverage`): a parsed,
   retainable Source Version (English; companyfacts excluded) the bank has no memory document
   of, with no triage, retain, poll or reprocess of it in flight and not every section skipped
   by triage: never submitted (`not_submitted`) or its triage failed after its attempts
   (`triage_failed`). Sampled as `<version id>:<reason>`.
8. `usage` (report only, never drift, errors included): Hindsight's LLM calls of the bank
   over its last day (`GET .../llm-requests/stats?period=1d`, one read per operation, retain,
   consolidation and reflect, and one for the total; the day buckets summed) with calls,
   errors and input, output and cached tokens, beside the units Atlas's budgets counted in the
   same window. The per-call listing is never read (each row carries the prompt and answer).

Each run is one insert-only `memory_reconciliation` row: the counts by kind, up to 20 sample
IDs each, the usage table and its `status`: `clean`, `drift`, or `failed` with the error
when a listing or read failed (no counts then: a partial result is never reported as clean).
The job is not pausable (no LLM) and no budget holds it; the worker enqueues one a day from
`ATLAS_RECONCILE_AT` (`ReconcileSchedule`), whether or not consolidation is on.
"""

import json
import uuid
from collections.abc import Mapping
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection, Engine, RowMapping, text

from atlas.bank_template import BankTemplate, InvalidTemplate
from atlas.hindsight import (
    HindsightError,
    HindsightGateway,
    HindsightNotFound,
    ListedDocument,
    ListedOperation,
)
from atlas.jobs.handlers import HandlerRegistry, Schedule
from atlas.jobs.pacing import Clock, utc_now
from atlas.jobs.queue import Artifacts, Enqueued, Job, JobQueue
from atlas.jobs.resources import hindsight_resources
from atlas.retention.backfill import IN_FLIGHT, STUCK, stuck_params
from atlas.retention.context import RETAIN_PROFILE
from atlas.retention.coverage import gaps, version_states
from atlas.settings import Settings

RECONCILE_KIND = "reconcile_memory"
type DriftKind = Literal[
    "section_missing",
    "document_unrecorded",
    "profile_mismatch",
    "observation_scope_outside",
    "config_drift",
    "consolidation_untracked",
    "version_not_in_memory",
]
DRIFT_KINDS: tuple[DriftKind, ...] = (
    "section_missing",
    "document_unrecorded",
    "profile_mismatch",
    "observation_scope_outside",
    "config_drift",
    "consolidation_untracked",
    "version_not_in_memory",
)
type ReconciliationStatus = Literal["clean", "drift", "failed"]
MAX_SAMPLES = 20
# The usage table's operations (`GET .../llm-requests/stats?period=1d&operation=`), one read
# each, and one without an operation for the bank's total.
USAGE_PERIOD = "1d"
USAGE_OPERATIONS = ("retain", "consolidation", "reflect")
# Atlas's documents are `srcv:<source version>:<anchor>`; others in the bank are not its.
ATLAS_DOCUMENT_PREFIX = "srcv:"
# Listing pages, and bounds on how much is read (a listing longer than its bound fails the
# run rather than reconcile half of it; the usage table only says it is incomplete).
DOCUMENT_PAGE = 500
MAX_DOCUMENT_PAGES = 400
SCOPE_PAGE = 1000
MAX_SCOPE_PAGES = 20
OPERATION_PAGE = 100
MAX_OPERATION_PAGES = 20
# The budgets whose units are Hindsight's work (`atlas.jobs.budget`): what usage sets beside it.
HINDSIGHT_PROVIDERS = ("codex", "hindsight_consolidation", "hindsight_minimax")
_RUNNING = frozenset({"pending", "processing"})
_RETAINED = frozenset({"completed", "zero_fact"})


class ReconcilePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scheduled_for: date | None = None  # the day a scheduled run is for; None: by hand


def reconcile_key(bank_id: str, day: date) -> str:
    """The idempotency key of a day's scheduled reconciliation."""
    return f"{RECONCILE_KIND}:{bank_id}:{day.isoformat()}"


def enqueue_reconciliation(
    queue: JobQueue, key: str, payload: ReconcilePayload | None = None
) -> Enqueued:
    """Ask for a reconciliation of the research bank (idempotent per key). Interactive class:
    it spends no budget, and a backfill window must not hold it from its night."""
    body = (payload or ReconcilePayload()).model_dump(mode="json")
    return queue.enqueue(RECONCILE_KIND, key, body)


class IncompleteListing(Exception):
    """A listing was longer than Atlas reads: the run cannot reconcile all of it."""


# --- the record ---------------------------------------------------------------------------------


class ReconciliationUsageRow(BaseModel):
    operation: str = Field(
        description="Hindsight's operation (retain, consolidation, reflect), or `total`: every"
        " call of the bank, these and the others"
    )
    calls: int
    errors: int = Field(description="calls whose status was not success (reported, never drift)")
    input_tokens: int
    output_tokens: int
    cached_tokens: int


class ReconciliationUsage(BaseModel):
    """Hindsight's LLM calls of the bank over the last day (`GET .../llm-requests/stats?
    period=1d`, its buckets summed), beside what Atlas's budgets counted."""

    since: datetime = Field(description="the start of Hindsight's period (the total's)")
    until: datetime
    hindsight: list[ReconciliationUsageRow] = Field(
        description="retain, consolidation, reflect, then the total"
    )
    atlas_counted: dict[str, int] = Field(
        description="units Atlas's budgets counted from `since` to `until`, by provider (codex"
        " and hindsight_minimax: operations submitted; hindsight_consolidation: rounds)"
    )


class ReconciliationSummary(BaseModel):
    id: uuid.UUID
    bank_id: str
    job_id: uuid.UUID | None
    status: ReconciliationStatus = Field(
        description="clean: no difference; drift: at least one; failed: a listing or read"
        " failed (see error) and nothing was counted"
    )
    error: str | None
    counts: dict[str, int] = Field(description="differences by kind (none when failed)")
    started_at: datetime
    ended_at: datetime


class ReconciliationRun(ReconciliationSummary):
    samples: dict[str, list[str]] = Field(
        description="up to 20 IDs per kind: Hindsight document IDs (section_missing,"
        " document_unrecorded, profile_mismatch), scopes' tags joined by commas"
        " (observation_scope_outside), setting names (config_drift), operation IDs or"
        " `run:<id>` (consolidation_untracked), `<version id>:<reason>` (version_not_in_memory)"
    )
    details: dict[str, dict[str, int]] = Field(
        description="a kind's count broken down (document_unrecorded by Atlas's state or"
        " `unknown`; profile_mismatch by what is lacking; consolidation_untracked by case)"
    )
    usage: ReconciliationUsage | None = Field(
        description="report only, never drift; none when failed"
    )


class _Found:
    """The differences of one run, kind by kind."""

    def __init__(self) -> None:
        self.ids: dict[DriftKind, list[str]] = {kind: [] for kind in DRIFT_KINDS}
        self.counts: dict[DriftKind, int] = dict.fromkeys(DRIFT_KINDS, 0)
        self.details: dict[DriftKind, dict[str, int]] = {}

    def add(
        self, kind: DriftKind, sample: str, *, weight: int = 1, detail: str | None = None
    ) -> None:
        self.ids[kind].append(sample)
        self.counts[kind] += weight
        if detail is not None:
            by = self.details.setdefault(kind, {})
            by[detail] = by.get(detail, 0) + weight

    def samples(self) -> dict[str, list[str]]:
        return {kind: sorted(ids)[:MAX_SAMPLES] for kind, ids in self.ids.items() if ids}


# --- the job ------------------------------------------------------------------------------------


class Reconciliation:
    """The `reconcile_memory` job for the research bank."""

    def __init__(
        self,
        engine: Engine,
        gateway: HindsightGateway,
        template_path: Path,
        *,
        clock: Clock = utc_now,
        stuck_after_hours: float,
    ) -> None:
        self._engine = engine
        self._gateway = gateway
        self._template_path = template_path
        self._clock = clock
        self._stuck_after_hours = stuck_after_hours

    @property
    def bank_id(self) -> str:
        return self._gateway.bank_id

    def run(self, job: Job | None = None) -> ReconciliationRun:
        """Reconcile once and record it (a job's retry returns the run it already recorded)."""
        if job is not None:
            with self._engine.connect() as connection:
                done = _read(connection, "job_id = :job", {"job": job.id})
            if done is not None:
                return done
        started = self._clock()
        found: _Found | None = None
        usage: ReconciliationUsage | None = None
        error: str | None = None
        try:
            template = BankTemplate.load(self._template_path)
            found = self._differences(template)
            usage = self._usage(started)
        except (HindsightError, IncompleteListing, InvalidTemplate) as failure:
            error = f"{type(failure).__name__}: {failure}"[:2000]
        ended = max(self._clock(), started)
        status: ReconciliationStatus
        if found is None:
            status = "failed"
        else:
            status = "drift" if any(found.counts.values()) else "clean"
        row: dict[str, Any] = {
            "id": uuid.uuid4(),
            "bank": self.bank_id,
            "job": job.id if job is not None else None,
            "started": started,
            "ended": ended,
            "status": status,
            "error": error,
            "counts": _json(dict(found.counts) if found else {}),
            "samples": _json(found.samples() if found else {}),
            "details": _json(dict(found.details) if found else {}),
            "usage": usage.model_dump_json() if usage is not None else None,
        }
        with self._engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO memory_reconciliation (id, bank_id, job_id, started_at,"
                    " ended_at, status, error, counts, samples, details, usage) VALUES (:id,"
                    " :bank, :job, :started, :ended, :status, :error, CAST(:counts AS jsonb),"
                    " CAST(:samples AS jsonb), CAST(:details AS jsonb), CAST(:usage AS jsonb))"
                ),
                row,
            )
            recorded = _read(connection, "id = :id", {"id": row["id"]})
        assert recorded is not None
        return recorded

    # --- the differences ---------------------------------------------------------------------

    def _differences(self, template: BankTemplate) -> _Found:
        found = _Found()
        documents = self._documents()
        # Atlas's records are read after the listing: a section retained meanwhile is absent
        # from it and confirmed present by its own read below; one deleted meanwhile by a
        # backfill is pending with its retain in flight by then.
        with self._engine.connect() as connection:
            sections = _sections(connection, self.bank_id, self._stuck_after_hours)
            run = _submitted_run(connection, self.bank_id)
            versions = gaps(version_states(connection, self.bank_id))
        self._missing(found, documents, sections)
        self._unrecorded(found, documents, sections)
        self._profiles(found, documents, sections)
        self._scopes(found)
        self._config(found, template)
        self._consolidations(found, run)
        for gap in versions:
            found.add(
                "version_not_in_memory",
                f"{gap.source_version_id}:{gap.state}",
                detail=gap.state,
            )
        return found

    def _documents(self) -> dict[str, ListedDocument]:
        listed: dict[str, ListedDocument] = {}
        for page in range(MAX_DOCUMENT_PAGES):
            batch = self._gateway.documents(limit=DOCUMENT_PAGE, offset=page * DOCUMENT_PAGE)
            listed.update((d.id, d) for d in batch.items if d.id.startswith(ATLAS_DOCUMENT_PREFIX))
            if not batch.items or (page + 1) * DOCUMENT_PAGE >= batch.total:
                return listed
        raise IncompleteListing(
            f"the bank lists more than {MAX_DOCUMENT_PAGES * DOCUMENT_PAGE} documents"
        )

    def _missing(
        self,
        found: _Found,
        documents: Mapping[str, ListedDocument],
        sections: Mapping[str, RowMapping],
    ) -> None:
        for document_id, section in sections.items():
            if section["retain_state"] not in _RETAINED or document_id in documents:
                continue
            try:
                self._gateway.get_document(document_id)
            except HindsightNotFound:
                found.add("section_missing", document_id, detail=section["retain_state"])

    def _unrecorded(
        self,
        found: _Found,
        documents: Mapping[str, ListedDocument],
        sections: Mapping[str, RowMapping],
    ) -> None:
        for document_id in documents:
            section = sections.get(document_id)
            if section is None:
                found.add("document_unrecorded", document_id, detail="unknown")
                continue
            state: str = section["retain_state"]
            stuck = state == "pending" and section["stuck"]
            lost = state in ("failed", "cancelled") and not section["in_flight"]
            if stuck or lost:
                found.add("document_unrecorded", document_id, detail=state)

    def _profiles(
        self,
        found: _Found,
        documents: Mapping[str, ListedDocument],
        sections: Mapping[str, RowMapping],
    ) -> None:
        for document_id, section in sections.items():
            document = documents.get(document_id)
            if (
                document is None
                or section["retain_state"] not in _RETAINED
                or section["retain_profile"] != RETAIN_PROFILE
            ):
                continue
            params = document.retain_params
            expected_scopes = {(tag,) for tag in document.tags if tag.startswith("theme:")}
            sent_scopes: set[tuple[str, ...]] = {
                tuple(s) for s in (params.observation_scopes if params else None) or []
            }
            expected_entities = set[str](section["retain_entities"] or [])
            sent_entities = params.entity_names() if params else set[str]()
            lacking = [
                name
                for name, missing in (
                    ("observation_scopes", not expected_scopes <= sent_scopes),
                    ("entities", not expected_entities <= sent_entities),
                )
                if missing
            ]
            if lacking:
                found.add("profile_mismatch", document_id, detail="+".join(lacking))

    def _scopes(self, found: _Found) -> None:
        read = 0
        for _ in range(MAX_SCOPE_PAGES):
            page = self._gateway.observation_scopes(limit=SCOPE_PAGE, offset=read)
            for scope in page.scopes:
                one_theme = len(scope.tags) == 1 and scope.tags[0].startswith("theme:")
                if not one_theme:
                    found.add("observation_scope_outside", ",".join(scope.tags), weight=scope.count)
            read += len(page.scopes)
            if not page.scopes or read >= page.total:
                return
        raise IncompleteListing(f"the bank lists more than {read} observation scopes")

    def _config(self, found: _Found, template: BankTemplate) -> None:
        settings = template.manifest.get("bank")
        if not isinstance(settings, dict):
            return
        # Every setting the template sets, whichever they are (the template grows: ticket 23).
        live = self._gateway.bank_config().config
        for name, value in sorted(settings.items()):
            if _normalized(live.get(name)) != _normalized(value):
                found.add("config_drift", name)

    def _consolidations(self, found: _Found, run: RowMapping | None) -> None:
        running = self._running_consolidations()
        anchor: datetime | None = None
        rounds: set[str] = set()
        last_ended = False
        if run is not None:
            rounds = set(run["rounds"] or []) | {run["operation_id"]}
            anchor = run["anchor_created_at"]
            last_id: str = run["last_operation_id"] or run["operation_id"]
            try:
                last = self._gateway.operation(last_id)
                last_ended = last.status not in _RUNNING
                if anchor is None and last_id == run["operation_id"]:
                    anchor = last.created_at
            except HindsightNotFound:
                last_ended = True
        followed = {
            o.id
            for o in running
            if run is not None
            and (
                o.id in rounds
                or (anchor is not None and o.created_at is not None and o.created_at >= anchor)
            )
        }
        for operation in running:
            if operation.id not in followed:
                found.add("consolidation_untracked", operation.id, detail="not_followed")
        if run is not None and last_ended and not followed:
            found.add("consolidation_untracked", f"run:{run['id']}", detail="run_ended")

    def _running_consolidations(self) -> list[ListedOperation]:
        running: dict[str, ListedOperation] = {}
        for status in ("pending", "processing"):
            for page in range(MAX_OPERATION_PAGES):
                listing = self._gateway.consolidation_operations(
                    status=status, limit=OPERATION_PAGE, offset=page * OPERATION_PAGE
                )
                running.update((o.id, o) for o in listing.operations if o.status in _RUNNING)
                if len(listing.operations) < OPERATION_PAGE:
                    break
            else:
                raise IncompleteListing(f"more {status} consolidation operations than read")
        return list(running.values())

    # --- usage ----------------------------------------------------------------------------------

    def _usage(self, until: datetime) -> ReconciliationUsage:
        """One stats read per operation and one for the total: counts and token sums only, so
        no call's prompt or answer is ever read."""
        rows: list[ReconciliationUsageRow] = []
        since = until
        for operation in (*USAGE_OPERATIONS, None):
            stats = self._gateway.llm_request_stats(period=USAGE_PERIOD, operation=operation)
            buckets = stats.buckets
            rows.append(
                ReconciliationUsageRow(
                    operation=operation or "total",
                    calls=sum(b.total for b in buckets),
                    errors=sum(
                        n
                        for b in buckets
                        for status, n in b.statuses.items()
                        if status != "success"
                    ),
                    input_tokens=sum(b.tokens.input for b in buckets),
                    output_tokens=sum(b.tokens.output for b in buckets),
                    cached_tokens=sum(b.tokens.cached for b in buckets),
                )
            )
            if operation is None:
                since = stats.start
        with self._engine.connect() as connection:
            counted = _counted(connection, since, until)
        return ReconciliationUsage(since=since, until=until, hindsight=rows, atlas_counted=counted)


def _normalized(value: object) -> object:
    """A setting's value as compared: a key whose value is absent, null, `{}` or `[]` is
    dropped from an object (the live bank stores the template's `entity_labels` groups with
    `"fields": {}` where the template has none), and an empty value is None. Object key order
    never matters (dict equality); list order is kept."""
    if isinstance(value, dict):
        items = cast(dict[object, object], value).items()
        kept = {str(k): _normalized(v) for k, v in items}
        return {k: v for k, v in kept.items() if v is not None} or None
    if isinstance(value, list):
        return [_normalized(item) for item in cast(list[object], value)] or None
    return value


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True)


def _sections(
    connection: Connection, bank_id: str, stuck_after_hours: float
) -> dict[str, RowMapping]:
    """The bank's sections Atlas records with a document ID, by that ID."""
    rows = connection.execute(
        text(
            "SELECT m.hindsight_document_id, m.retain_state, m.retain_profile,"  # noqa: S608 (constant fragments)
            f" m.retain_entities, {STUCK} AS stuck, {IN_FLIGHT} AS in_flight"
            " FROM memory_document m WHERE m.bank_id = :bank"
            " AND m.hindsight_document_id IS NOT NULL"
        ),
        {"bank": bank_id, **stuck_params(stuck_after_hours)},
    ).mappings()
    return {row["hindsight_document_id"]: row for row in rows}


def _submitted_run(connection: Connection, bank_id: str) -> RowMapping | None:
    """The bank's run of Atlas still `submitted` (at most one), with its rounds and the
    created time of the operation it requested."""
    return (
        connection.execute(
            text(
                "SELECT c.id, c.operation_id, c.last_operation_id,"
                " (SELECT array_agg(r.operation_id) FROM memory_consolidation_round r"
                "   WHERE r.consolidation_id = c.id) AS rounds,"
                " (SELECT r.created_at FROM memory_consolidation_round r"
                "   WHERE r.operation_id = c.operation_id) AS anchor_created_at"
                " FROM memory_consolidation c WHERE c.bank_id = :bank AND c.status = 'submitted'"
            ),
            {"bank": bank_id},
        )
        .mappings()
        .one_or_none()
    )


def _counted(connection: Connection, since: datetime, until: datetime) -> dict[str, int]:
    counted: dict[str, int] = dict.fromkeys(HINDSIGHT_PROVIDERS, 0)
    for provider, units in connection.execute(
        text(
            "SELECT provider, sum(units) FROM provider_usage WHERE provider = ANY(:providers)"
            " AND recorded_at > :since AND recorded_at <= :until GROUP BY 1"
        ),
        {"providers": list(HINDSIGHT_PROVIDERS), "since": since, "until": until},
    ).all():
        counted[provider] = int(units)
    return counted


# --- reads --------------------------------------------------------------------------------------

_COLUMNS = (
    "id, bank_id, job_id, started_at, ended_at, status, error, counts, samples, details, usage"
)


def _read(
    connection: Connection, where: str, params: Mapping[str, Any]
) -> ReconciliationRun | None:
    row = (
        connection.execute(
            text(f"SELECT {_COLUMNS} FROM memory_reconciliation WHERE {where}"),  # noqa: S608 (constant fragments)
            params,
        )
        .mappings()
        .one_or_none()
    )
    return None if row is None else ReconciliationRun.model_validate(dict(row))


def get_reconciliation(
    connection: Connection, reconciliation_id: uuid.UUID
) -> ReconciliationRun | None:
    return _read(connection, "id = :id", {"id": reconciliation_id})


def list_reconciliations(
    connection: Connection, bank_id: str, *, limit: int, offset: int
) -> tuple[list[ReconciliationSummary], int]:
    """The bank's runs, newest first, and how many there are."""
    rows = connection.execute(
        text(
            f"SELECT {_COLUMNS} FROM memory_reconciliation WHERE bank_id = :bank"  # noqa: S608 (constant fragments)
            " ORDER BY started_at DESC, recorded_at DESC, id LIMIT :limit OFFSET :offset"
        ),
        {"bank": bank_id, "limit": limit, "offset": offset},
    ).mappings()
    total = connection.execute(
        text("SELECT count(*) FROM memory_reconciliation WHERE bank_id = :bank"),
        {"bank": bank_id},
    ).scalar_one()
    return [ReconciliationSummary.model_validate(dict(row)) for row in rows], int(total)


def last_reconciliation(connection: Connection, bank_id: str) -> ReconciliationSummary | None:
    """The bank's latest run, whatever its status (the health read's `reconciliation`)."""
    runs, _ = list_reconciliations(connection, bank_id, limit=1, offset=0)
    return runs[0] if runs else None


# --- the worker's handler and schedule ----------------------------------------------------------


class ReconcileSchedule:
    """Enqueues the day's reconciliation from `at` (UTC), once a day."""

    def __init__(self, engine: Engine, bank_id: str, at: time) -> None:
        self._engine = engine
        self._bank_id = bank_id
        self._at = at
        self._done: date | None = None

    def __call__(self, now: datetime) -> list[Enqueued]:
        moment = now.astimezone(UTC)
        day = moment.date()
        if self._done == day or moment.time() < self._at:
            return []
        queue = JobQueue(self._engine)  # audited as the system actor's: Atlas schedules it
        payload = ReconcilePayload(scheduled_for=day)
        enqueued = enqueue_reconciliation(queue, reconcile_key(self._bank_id, day), payload)
        self._done = day
        return [enqueued]


def register_reconciliation_handlers(
    registry: HandlerRegistry, settings: Settings, clock: Clock = utc_now
) -> None:
    def reconcile(job: Job) -> Artifacts:
        ReconcilePayload.model_validate(job.payload)
        with hindsight_resources(settings) as (gateway, engine):
            found = Reconciliation(
                engine,
                gateway,
                settings.hindsight_template_path,
                clock=clock,
                stuck_after_hours=settings.backfill_stuck_after_hours,
            ).run(job)
        return {
            "reconciliation_id": str(found.id),
            "status": found.status,
            "counts": dict(found.counts),
            "error": found.error,
        }

    # Not pausable: it calls no LLM, so no quota or outage pause holds it (a Hindsight that
    # cannot answer makes the run `failed`, recorded).
    registry.register(RECONCILE_KIND, reconcile)


def reconciliation_schedules(settings: Settings, engine: Engine) -> list[Schedule]:
    """The daily reconciliation (none without Hindsight or with an empty schedule; it runs
    whether or not consolidation is on)."""
    if not settings.hindsight_url or not settings.reconcile_at:
        return []
    hour, minute = (int(part) for part in settings.reconcile_at.split(":"))
    return [ReconcileSchedule(engine, settings.hindsight_bank_id, time(hour, minute))]
