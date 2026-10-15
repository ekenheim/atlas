"""A Fact is recorded once per span: the second session reuses it (atlas-beliefs ticket 26).

The MCP session on question 2 (`19c130c7`, 15 October) took 35 of its 38 Facts from documents the
closing session had cited already, and 15 overlapped a span already recorded: a session that
starts from nothing records again what Atlas holds. A Fact recorded in a research session for a
span that overlaps a standing Fact of the same Source Version, company and step is therefore not
recorded again. `decide` says which of three it is, over the Facts that overlap:

- **reuse**: one of them has the candidate's status and an alike statement
  (`atlas.facts.duplicates.alike`: word-set Jaccard >= 0.5). The existing Fact is returned, no
  row is made, and the session records that it reused it (`session_fact_reuse`);
- **same span**: none does, so the statement is materially different (another status, or other
  words): a new Fact is recorded and names the first overlapping one (`same_span_as`);
- **new**: nothing overlaps.

A Fact whose Assertion was disputed, rejected or superseded is not reused. The step must be the
same: one sentence may bear on two steps, and the second step's Fact is its own. Reuse never
edits or deletes an insert-only record: it returns the row that exists.
"""

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import Connection, text

from atlas.facts.duplicates import FactSpan, alike

STANDING = ("unreviewed", "corroborated")


@dataclass(frozen=True)
class Decision:
    kind: Literal["new", "reuse", "same_span"]
    fact_id: uuid.UUID | None = None  # the Fact reused, or the one the new Fact names


def decide(candidate: FactSpan, existing: Iterable[FactSpan]) -> Decision:
    """Reuse, same span or new, over `existing` (oldest first): the Facts of the candidate's
    Source Version, company and step that stand. Facts of another version, company or step are
    left out whatever they say, so a caller may pass a wider list."""
    first: FactSpan | None = None
    for other in existing:
        if (
            other.source_version_id != candidate.source_version_id
            or other.company_id != candidate.company_id
            or other.step != candidate.step
            or not (candidate.span_start < other.span_end and other.span_start < candidate.span_end)
        ):
            continue
        if other.status == candidate.status and alike(other.statement, candidate.statement):
            return Decision("reuse", other.fact_id)
        first = first or other
    if first is None:
        return Decision("new")
    return Decision("same_span", first.fact_id)


def overlapping(connection: Connection, candidate: FactSpan) -> list[FactSpan]:
    """The standing Facts of the candidate's Source Version, company and step that overlap its
    span, oldest first."""
    rows = connection.execute(
        text(
            "SELECT f.assertion_id, a.source_version_id, a.subject_company_id, a.span_start,"
            " a.span_end, a.quote, f.status, a.value_json->>'statement' AS statement, f.step"
            " FROM fact f JOIN assertion a ON a.id = f.assertion_id"
            " WHERE a.source_version_id = :version AND a.subject_company_id = :company"
            " AND f.step = :step AND a.verification_status = ANY(:standing)"
            " AND a.span_start < :end AND :start < a.span_end"
            " ORDER BY f.created_at, f.assertion_id"
        ),
        {
            "version": candidate.source_version_id,
            "company": candidate.company_id,
            "step": candidate.step,
            "standing": list(STANDING),
            "start": candidate.span_start,
            "end": candidate.span_end,
        },
    )
    return [
        FactSpan(
            fact_id=row.assertion_id,
            source_version_id=row.source_version_id,
            company_id=row.subject_company_id,
            span_start=row.span_start,
            span_end=row.span_end,
            quote=row.quote,
            status=row.status,
            statement=row.statement,
            step=row.step,
            session_key=None,
        )
        for row in rows
    ]
