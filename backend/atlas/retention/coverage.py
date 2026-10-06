"""Which parsed Source Versions Memory holds, and which it was never offered (pilot-review
ticket 22; `docs/decisions.md`, "Every parsed version reaches Memory"; `docs/runbooks.md`,
"Memory backfill").

Memory health counted recorded sections only, so a Source Version nothing ever submitted (an
ingest cut short by `--max-retains`) or whose triage failed after its attempts showed nowhere:
no section, no failed state, a clean reconciliation. This module classifies every version
Memory **should** hold, by the rule the retain path already uses (`RETAINABLE_PARSES` and
`RETAINABLE_LANGUAGES` of `atlas.retention.service`: a `parsed` or `incomplete` parse in
English; a companyfacts version has no parse and a French or Chinese one is archived, not
retained), into exactly one state, the first that applies:

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
    "in_memory", "in_flight", "triage_failed", "all_skipped", "not_submitted"
]
type GapReason = Literal["not_submitted", "triage_failed"]
GAP_REASONS: tuple[GapReason, ...] = ("not_submitted", "triage_failed")

# The CASE of `version_states`: v is the Source Version, `:bank` the research bank. A version
# whose latest triage job is queued or running is in flight (the first two arms), so a retry
# in progress is not a failure, and a failed job later retried is judged by the retry.
_STATE = (
    "CASE"
    " WHEN EXISTS (SELECT FROM memory_document m WHERE m.source_version_id = v.id"
    "   AND m.bank_id = :bank) THEN 'in_memory'"
    " WHEN EXISTS (SELECT FROM job j WHERE j.status IN ('queued', 'running') AND ("
    "   (j.kind IN ('triage', 'retain')"
    "     AND j.payload ->> 'source_version_id' = CAST(v.id AS text))"
    "   OR (j.kind IN ('poll_operation', 'reprocess')"
    "     AND j.payload ->> 'operation_id' IN (SELECT o.id FROM hindsight_operation o"
    "       WHERE o.source_version_id = v.id)))) THEN 'in_flight'"
    " WHEN (SELECT j.status FROM job j WHERE j.kind = 'triage'"
    "   AND j.payload ->> 'source_version_id' = CAST(v.id AS text)"
    "   ORDER BY j.created_at DESC, j.id DESC LIMIT 1) = 'failed' THEN 'triage_failed'"
    " WHEN EXISTS (SELECT FROM triage_decision t WHERE t.source_version_id = v.id)"
    "   AND NOT EXISTS (SELECT FROM triage_decision t WHERE t.source_version_id = v.id"
    "     AND t.decision = 'retain' AND NOT EXISTS (SELECT FROM triage_decision later"
    "       WHERE later.source_version_id = t.source_version_id"
    "       AND later.section_anchor = t.section_anchor AND later.seq > t.seq))"
    "   THEN 'all_skipped'"
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
    connection: Connection, bank_id: str, company_id: uuid.UUID | None = None
) -> list[VersionRow]:
    """Every parsed Source Version Memory should hold (of one company, or all), newest first by
    availability, with its state."""
    rows = connection.execute(
        text(
            "SELECT v.id AS source_version_id, d.company_id, c.slug AS company_slug,"  # noqa: S608 (constant fragments)
            f" d.title, a.available_at, {_STATE} AS state"
            " FROM source_version v"
            " JOIN source_version_availability a ON a.source_version_id = v.id"
            " JOIN source_document d ON d.id = v.source_document_id"
            " LEFT JOIN company c ON c.id = d.company_id"
            " WHERE v.parse_status = ANY(:parses) AND v.language = ANY(:languages)"
            " AND (CAST(:company AS uuid) IS NULL OR d.company_id = :company)"
            " ORDER BY a.available_at DESC, v.id"
        ),
        {
            "bank": bank_id,
            "company": company_id,
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
