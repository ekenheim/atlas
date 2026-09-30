"""The read side of Claims: each proposed Claim's outcome, and each extraction's progress."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, JsonValue
from sqlalchemy import Connection, text

ClaimOutcome = Literal["accepted", "rejected"]
ExtractionStatus = Literal["running", "completed", "budget_exhausted"]
OffsetSource = Literal["model", "located"]


class Passage(BaseModel):
    """A stretch of one Source Version's parsed text sent to the Investigator."""

    model_config = ConfigDict(frozen=True)

    id: str
    source_version_id: uuid.UUID
    section_anchor: str
    char_start: int
    char_end: int
    # Why it was chosen: `entity:<company_id>` (the text names that company) and/or `recall`
    # (a recall hit for the extraction's question resolved to its section), or `lead` alone (a
    # lead window of a document with neither, sent for its share of the passage budget).
    selected_by: list[str]


class SkippedVersion(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_version_id: uuid.UUID
    reason: str


class Claim(BaseModel):
    """One proposed Claim and its outcome. `proposed` is the Claim exactly as the model
    answered; the other fields are what Atlas resolved from it (null when it couldn't)."""

    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    extraction_id: uuid.UUID
    run_id: uuid.UUID
    role_call_id: uuid.UUID
    passage_id: str
    source_version_id: uuid.UUID | None
    subject_company_id: uuid.UUID | None
    predicate: str
    object_company_id: uuid.UUID | None
    object_text: str | None
    product: str | None
    layer: str
    quote: str
    span_start: int | None
    span_end: int | None
    epistemic_type: str
    directional_cue: str | None
    outcome: ClaimOutcome
    reason_code: str | None
    reason: str | None
    assertion_id: uuid.UUID | None
    # Where the span came from once the quote was placed: `model` (the quote was exactly at the
    # model's offsets, kept in `proposed`) or `located` (Atlas found its one exact occurrence in
    # the passage). Null when the quote was never placed, or recorded before migration 0024.
    offset_source: OffsetSource | None
    proposed: dict[str, JsonValue]
    created_at: datetime


class ClaimExtraction(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    job_id: uuid.UUID
    run_id: uuid.UUID
    source_version_ids: list[uuid.UUID]
    question: str | None
    status: ExtractionStatus
    passages: list[Passage]
    passages_dropped: int
    passages_per_call: int
    skipped: list[SkippedVersion]
    batches_total: int
    batches_done: int
    # The budget-exhausted extraction this one continues (its remaining passages), if any.
    continues_id: uuid.UUID | None
    batches_quarantined: int
    accepted: int
    rejected: int
    started_at: datetime
    finished_at: datetime | None


_FILTER = """
    WHERE (CAST(:extraction AS uuid) IS NULL OR extraction_id = :extraction)
      AND (CAST(:run AS uuid) IS NULL OR run_id = :run)
      AND (CAST(:version AS uuid) IS NULL OR source_version_id = :version)
      AND (CAST(:outcome AS text) IS NULL OR outcome = :outcome)
      AND (CAST(:reason AS text) IS NULL OR reason_code = :reason)
"""


def list_claims(
    connection: Connection,
    *,
    extraction_id: uuid.UUID | None = None,
    run_id: uuid.UUID | None = None,
    source_version_id: uuid.UUID | None = None,
    outcome: ClaimOutcome | None = None,
    reason_code: str | None = None,
    limit: int,
    offset: int,
) -> tuple[list[Claim], int]:
    """Claims oldest first (in the order they were proposed)."""
    params: dict[str, Any] = {
        "extraction": extraction_id,
        "run": run_id,
        "version": source_version_id,
        "outcome": outcome,
        "reason": reason_code,
        "limit": limit,
        "offset": offset,
    }
    total = connection.execute(text(f"SELECT count(*) FROM claim {_FILTER}"), params)  # noqa: S608 (constant fragments)
    rows = connection.execute(
        text(
            f"SELECT * FROM claim {_FILTER}"  # noqa: S608 (constant fragments)
            " ORDER BY created_at, role_call_id, ordinal LIMIT :limit OFFSET :offset"
        ),
        params,
    ).mappings()
    return [Claim.model_validate(dict(row)) for row in rows], total.scalar_one()


def get_claim(connection: Connection, claim_id: uuid.UUID) -> Claim | None:
    row = (
        connection.execute(text("SELECT * FROM claim WHERE id = :id"), {"id": claim_id})
        .mappings()
        .one_or_none()
    )
    return None if row is None else Claim.model_validate(dict(row))


def get_extraction(connection: Connection, extraction_id: uuid.UUID) -> ClaimExtraction | None:
    row = (
        connection.execute(
            text(
                "SELECT e.*,"
                " (SELECT count(*) FROM claim c WHERE c.extraction_id = e.id"
                "  AND c.outcome = 'accepted') AS accepted,"
                " (SELECT count(*) FROM claim c WHERE c.extraction_id = e.id"
                "  AND c.outcome = 'rejected') AS rejected"
                " FROM claim_extraction e WHERE e.id = :id"
            ),
            {"id": extraction_id},
        )
        .mappings()
        .one_or_none()
    )
    return None if row is None else ClaimExtraction.model_validate(dict(row))
