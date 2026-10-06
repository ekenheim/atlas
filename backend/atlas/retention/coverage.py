"""Which parsed Source Versions Memory holds, and which it was never offered (pilot-review
ticket 22; `docs/decisions.md`, "Every parsed version reaches Memory"; `docs/runbooks.md`,
"Memory backfill").

Memory health counted recorded sections only, so a Source Version nothing ever submitted (an
ingest cut short by `--max-retains`) or whose triage failed after its attempts showed nowhere:
no section, no failed state, a clean reconciliation. This module classifies every version
Memory **should** hold, by the rule the retain path already uses (`RETAINABLE_PARSES` and
`RETAINABLE_LANGUAGES` of `atlas.retention.service`: a `parsed` or `incomplete` parse in
English; a companyfacts version has no parse and a French or Chinese one is archived, not
retained), into exactly one state, the first that applies (only a document's current version counts:
a superseded one that never reached Memory is not a gap):

- `in_memory`: the bank has a memory document of it (a section in any retain state, or linked);
- `in_flight`: a `triage`, `retain`, `poll_operation` or `reprocess` of it is queued or running;
- `triage_failed`: its latest `triage` job failed after its attempts (`atlas triage retry`);
- `all_skipped`: triage decided it and every section's effective decision is `skip`;
- `not_submitted`: none of these; nothing of it was offered to Memory, or what was offered
  was lost (a retain job that failed, decisions to retain that no job followed).

`not_submitted` and `triage_failed` are the **gaps**: the health read shows them per company
and for the bank with samples, the reconciliation reports them as drift
(`version_not_in_memory`), `atlas_versions_not_in_memory{company,reason}` counts them, and
`atlas memory backfill` takes them.
"""

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import Connection, text

from atlas.retention.service import RETAINABLE_LANGUAGES, RETAINABLE_PARSES

MAX_SAMPLES = 20
type VersionState = Literal[
    "in_memory", "retired", "in_flight", "triage_failed", "all_skipped", "not_submitted"
]
type GapReason = Literal["not_submitted", "triage_failed"]
GAP_REASONS: tuple[GapReason, ...] = ("not_submitted", "triage_failed")

# The facts `version_states` joins to each version, each computed once over its table (the
# state is read at every metrics scrape: no per-version subquery against `job`, which has no
# index on its payload). A version whose latest triage job is queued or running is in flight
# (`flight`), so a retry in progress is not a failure, and a failed job later retried is
# judged by the retry (`latest_triage`).
_FACTS = (
    "WITH mem AS (SELECT DISTINCT source_version_id AS id FROM memory_document"
    "   WHERE bank_id = :bank AND retain_state <> 'retired'),"
    " retired AS (SELECT DISTINCT source_version_id AS id FROM memory_document"
    "   WHERE bank_id = :bank AND retain_state = 'retired'),"
    " flight AS ("
    "   SELECT DISTINCT j.payload ->> 'source_version_id' AS id FROM job j"
    "    WHERE j.status IN ('queued', 'running') AND j.kind IN ('triage', 'retain')"
    "   UNION"
    "   SELECT o.source_version_id::text FROM job j"
    "    JOIN hindsight_operation o ON o.id = j.payload ->> 'operation_id'"
    "    WHERE j.status IN ('queued', 'running') AND j.kind IN ('poll_operation', 'reprocess')),"
    " latest_triage AS ("
    "   SELECT DISTINCT ON (payload ->> 'source_version_id')"
    "    payload ->> 'source_version_id' AS id, status FROM job WHERE kind = 'triage'"
    "    ORDER BY payload ->> 'source_version_id', created_at DESC, id DESC),"
    " decided AS ("
    "   SELECT source_version_id AS id, bool_or(decision = 'retain') AS has_retain FROM ("
    "    SELECT DISTINCT ON (source_version_id, section_anchor) source_version_id, decision"
    "    FROM triage_decision ORDER BY source_version_id, section_anchor, seq DESC) effective"
    "   GROUP BY 1)"
)
_STATE = (
    "CASE WHEN mem.id IS NOT NULL THEN 'in_memory'"
    " WHEN retired.id IS NOT NULL THEN 'retired'"
    " WHEN flight.id IS NOT NULL THEN 'in_flight'"
    " WHEN latest_triage.status = 'failed' THEN 'triage_failed'"
    " WHEN decided.id IS NOT NULL AND NOT decided.has_retain THEN 'all_skipped'"
    " ELSE 'not_submitted' END"
)


class VersionSample(BaseModel):
    source_version_id: uuid.UUID
    title: str
    available_at: datetime


class VersionCounts(BaseModel):
    """The parsed, retainable Source Versions Memory should hold, by what became of them."""

    total: int = 0
    in_memory: int = Field(default=0, description="the bank holds a memory document of it")
    retired: int = Field(
        default=0, description="its sections were retired (`atlas memory retire`): not a gap"
    )
    all_skipped: int = Field(
        default=0, description="triage decided it and every effective decision is `skip`"
    )
    triage_failed: int = Field(
        default=0, description="its latest triage job failed after its attempts"
    )
    in_flight: int = Field(
        default=0, description="a triage, retain, poll or reprocess of it is queued or running"
    )
    not_submitted: int = Field(
        default=0, description="none of these: nothing of it was offered to Memory"
    )
    not_submitted_samples: list[VersionSample] = Field(
        default_factory=list[VersionSample], description="up to 20, newest first"
    )
    triage_failed_samples: list[VersionSample] = Field(
        default_factory=list[VersionSample], description="up to 20, newest first"
    )


class VersionRow(BaseModel):
    source_version_id: uuid.UUID
    company_id: uuid.UUID | None
    company_slug: str | None
    title: str
    available_at: datetime
    state: VersionState


def version_states(
    connection: Connection,
    bank_id: str,
    company_id: uuid.UUID | None = None,
    *,
    window_days: int | None = None,
) -> list[VersionRow]:
    """Every parsed Source Version Memory should hold (of one company, or all), newest first by
    availability, with its state. With `window_days` (the intake window,
    `ATLAS_INGEST_LOOKBACK_DAYS`), a version available before the window is Memory's only while
    it is still there or was retired from it: one never retained is not a gap (Memory holds the
    intake window; `docs/decisions.md`)."""
    rows = connection.execute(
        text(
            f"{_FACTS}"  # noqa: S608 (constant fragments)
            " SELECT v.id AS source_version_id, d.company_id, c.slug AS company_slug,"
            f" d.title, a.available_at, {_STATE} AS state"
            " FROM source_version v"
            " JOIN source_version_availability a ON a.source_version_id = v.id"
            " JOIN source_document d ON d.id = v.source_document_id"
            " LEFT JOIN company c ON c.id = d.company_id"
            " LEFT JOIN mem ON mem.id = v.id"
            " LEFT JOIN retired ON retired.id = v.id"
            " LEFT JOIN flight ON flight.id = CAST(v.id AS text)"
            " LEFT JOIN latest_triage ON latest_triage.id = CAST(v.id AS text)"
            " LEFT JOIN decided ON decided.id = v.id"
            " WHERE v.parse_status = ANY(:parses) AND v.language = ANY(:languages)"
            # Only a document's current version: a superseded one is not a gap.
            " AND NOT EXISTS (SELECT FROM source_version n WHERE n.supersedes_version_id = v.id)"
            " AND (CAST(:company AS uuid) IS NULL OR d.company_id = :company)"
            " AND (CAST(:window AS integer) IS NULL OR mem.id IS NOT NULL OR retired.id IS NOT NULL"
            "   OR a.available_at >= now() - make_interval(days => CAST(:window AS integer)))"
            " ORDER BY a.available_at DESC, v.id"
        ),
        {
            "bank": bank_id,
            "company": company_id,
            "window": window_days,
            "parses": list(RETAINABLE_PARSES),
            "languages": list(RETAINABLE_LANGUAGES),
        },
    ).mappings()
    return [VersionRow.model_validate(dict(row)) for row in rows]


def count_versions(rows: Sequence[VersionRow]) -> VersionCounts:
    """The rows' counts and gap samples."""
    counts = VersionCounts()
    for row in rows:
        counts.total += 1
        setattr(counts, row.state, getattr(counts, row.state) + 1)
        sample = VersionSample(
            source_version_id=row.source_version_id, title=row.title, available_at=row.available_at
        )
        if row.state == "not_submitted" and len(counts.not_submitted_samples) < MAX_SAMPLES:
            counts.not_submitted_samples.append(sample)
        if row.state == "triage_failed" and len(counts.triage_failed_samples) < MAX_SAMPLES:
            counts.triage_failed_samples.append(sample)
    return counts


def counts_by_company(rows: Sequence[VersionRow]) -> dict[uuid.UUID | None, VersionCounts]:
    grouped: dict[uuid.UUID | None, list[VersionRow]] = {}
    for row in rows:
        grouped.setdefault(row.company_id, []).append(row)
    return {company: count_versions(group) for company, group in grouped.items()}


def gaps(rows: Sequence[VersionRow]) -> list[VersionRow]:
    """The versions Memory should hold and was never given (or lost): `not_submitted` and
    `triage_failed`."""
    return [row for row in rows if row.state in GAP_REASONS]
