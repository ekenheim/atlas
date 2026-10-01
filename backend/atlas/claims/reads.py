"""The read side of Claims: each proposed Claim's outcome, and each extraction's progress."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue
from sqlalchemy import Connection, text

ClaimOutcome = Literal["accepted", "rejected"]
ExtractionStatus = Literal["running", "completed", "budget_exhausted"]
OffsetSource = Literal["model", "located", "folded"]
PartyBasis = Literal["named", "filer"]
LayerReason = Literal["layer_unsupported"]


class Passage(BaseModel):
    """A stretch of one Source Version's parsed text sent to the Investigator."""

    model_config = ConfigDict(frozen=True)

    id: str
    source_version_id: uuid.UUID
    section_anchor: str
    char_start: int
    char_end: int
    # Every selection that chose it (atlas.claims.selection): `pointer:<query_index>` (a
    # reading pointer's window: the question's, index 0, or a Scout query's), `search` (it
    # contains a term of the question or the Scout's queries), `entity:<company_id>` (it names
    # that company), or `lead` alone (a lead window of a document with none of those).
    # Extractions made before memory-directed reading ticket 05 have `recall` (a recall hit
    # resolved to its section) instead of `pointer` and `search`.
    selected_by: list[str]
    # The parse of the Source Version the offsets are in (pilot-fixes ticket 11): the current
    # parse when the extraction started. None for passages chosen before migration 0046, which
    # are in the version's recorded parse.
    parser_version: str | None = None


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
    # The selections that chose that passage (its `selected_by` in the Claim's extraction):
    # which of pointer, search, entity or lead found what the Claim quotes. Empty when the
    # Claim names no passage that was sent.
    passage_selected_by: list[str] = Field(default_factory=list[str])
    source_version_id: uuid.UUID | None
    subject_company_id: uuid.UUID | None
    predicate: str
    object_company_id: uuid.UUID | None
    object_text: str | None
    product: str | None
    # An accepted Claim's layer: the proposed one, kept only when a taxonomy term of it
    # (`layer_term`) occurs in the object text or the quote; else null. A rejected Claim's is
    # the layer as proposed (null when none was). The proposal is always in `proposed`.
    layer: str | None
    # The words of the object text or the quote that support an accepted Claim's layer. Null
    # when it has none, for a rejected Claim, and for Claims recorded before migration 0055.
    layer_term: str | None = None
    # `layer_unsupported`: the accepted Claim proposed a layer that neither its quote nor its
    # object names, so it has none. Null otherwise.
    layer_reason: LayerReason | None = None
    # The archived text at the span once the quote was placed and the Claim accepted (the
    # model's spelling, which the typographic fold may have bridged, stays in `proposed`);
    # the quote as proposed otherwise.
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
    # model's offsets, kept in `proposed`), `located` (Atlas found its one exact occurrence in
    # the passage) or `folded` (it matched only through the typographic fold: hyphens, quotation
    # marks, spaces). Null when the quote was never placed, or recorded before migration 0024.
    offset_source: OffsetSource | None
    # How an accepted Claim's quote identifies its parties: `named` (each by name, or the filer
    # in the first person) or `filer` (the filer is the unnamed party of an impersonal sentence
    # of its own document). Null for a rejected Claim and for Claims recorded before migration
    # 0052.
    party_basis: PartyBasis | None = None
    # The parse of the Source Version its passage was cut from (and its span is in). Null for
    # Claims recorded before migration 0046 (the recorded parse) and for an unknown passage.
    parser_version: str | None = None
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
# The `selected_by` of claim `c`'s passage in its extraction (an SQL expression): `[]` when
# the Claim names no passage the extraction holds.
PASSAGE_SELECTED_BY = """
    coalesce((SELECT p -> 'selected_by' FROM claim_extraction e,
              jsonb_array_elements(e.passages) p
              WHERE e.id = c.extraction_id AND p ->> 'id' = c.passage_id LIMIT 1),
             '[]'::jsonb)
"""
_CLAIMS = f"SELECT c.*, {PASSAGE_SELECTED_BY} AS passage_selected_by FROM claim c"  # noqa: S608 (constant fragments)


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
            f"{_CLAIMS} {_FILTER}"
            " ORDER BY created_at, role_call_id, ordinal LIMIT :limit OFFSET :offset"
        ),
        params,
    ).mappings()
    return [Claim.model_validate(dict(row)) for row in rows], total.scalar_one()


def get_claim(connection: Connection, claim_id: uuid.UUID) -> Claim | None:
    row = (
        connection.execute(text(f"{_CLAIMS} WHERE c.id = :id"), {"id": claim_id})
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
