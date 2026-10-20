"""Storing and reading the rewrite check's findings (atlas-record ticket 02).

`check_rewrites` runs inside `Editions.import_page`'s transaction, right after the edition's row
is inserted and under the theme's advisory lock, so an edition and its findings commit together
(never an edition without its check) and the previous edition cannot change between the lookup
and the insert. The previous edition is the theme's latest parsed one before this one, ordered
by `as_of`, then edition number, then the order Atlas read them in (the last so that a page
rewritten the same day is compared with the one it rewrote). An edition that did not parse is
neither compared nor a previous edition. The pure comparison is `atlas.record.rewrites`.

An edition imported out of order (an older `as_of` after a newer one is stored) is compared with
its own predecessor only; the newer edition is not checked again against it.
"""

import json
import uuid
from datetime import date, datetime
from typing import Any, cast

from pydantic import BaseModel, Field
from sqlalchemy import Connection, Engine, text

from atlas.record.ledger import CouncilLedger, Ledger, ThemeLedger
from atlas.record.rewrites import Rewrite, RewriteKind, compare_ledgers

_COLUMNS = (
    "r.id, r.edition_id, r.previous_edition_id, e.theme, e.as_of, r.kind, r.subject_id,"
    " r.field, r.before, r.after, r.found_at"
)
_FROM = " FROM ledger_rewrite r JOIN ledger_edition e ON e.id = r.edition_id"
_ORDER = " ORDER BY e.as_of DESC, e.seq DESC, r.seq ASC"


class RewriteRecord(BaseModel):
    id: uuid.UUID
    edition_id: uuid.UUID = Field(description="the edition that rewrote an earlier one")
    previous_edition_id: uuid.UUID = Field(description="the edition it was compared with")
    theme: str = Field(description="the theme's slug; `council` for the council's")
    as_of: date = Field(description="the edition's as-of day")
    kind: RewriteKind
    subject_id: str = Field(
        description="the prediction, chokepoint, board item or contradiction it is about"
        " (the theme's slug for an edition number)"
    )
    field: str | None = Field(description="the field that differs, when one does")
    before: Any = Field(description="the previous edition's value")
    after: Any = Field(description="this edition's value; null when it is gone")
    found_at: datetime = Field(description="when Atlas stored the edition and found it")


def _ledger(raw: object) -> Ledger | None:
    if not isinstance(raw, dict):
        return None
    body = cast("dict[str, Any]", raw)
    if "chokepoints" in body:
        return ThemeLedger.model_validate(body)
    return CouncilLedger.model_validate(body)


def check_rewrites(
    connection: Connection,
    edition_id: uuid.UUID,
    theme: str,
    ledger: Ledger,
    found_at: datetime,
) -> list[Rewrite]:
    """Compare the stored edition with the theme's previous parsed one and record every
    difference. Returns the findings (none when there is no previous edition)."""
    previous = connection.execute(
        text(
            "SELECT id, ledger FROM ledger_edition"
            " WHERE theme = :theme AND ledger IS NOT NULL AND id <> :id"
            " AND (as_of, edition, seq) < (SELECT as_of, edition, seq FROM ledger_edition"
            " WHERE id = :id)"
            " ORDER BY as_of DESC, edition DESC, seq DESC LIMIT 1"
        ),
        {"theme": theme, "id": edition_id},
    ).one_or_none()
    if previous is None:
        return []
    before = _ledger(previous.ledger)
    if before is None:
        return []
    findings = compare_ledgers(ledger, before)
    for finding in findings:
        connection.execute(
            text(
                "INSERT INTO ledger_rewrite (id, edition_id, previous_edition_id, kind,"
                " subject_id, field, before, after, found_at)"
                " VALUES (:id, :edition, :previous, :kind, :subject, :field,"
                " CAST(:before AS jsonb), CAST(:after AS jsonb), :found_at)"
            ),
            {
                "id": uuid.uuid4(),
                "edition": edition_id,
                "previous": previous.id,
                "kind": finding.kind,
                "subject": finding.subject_id,
                "field": finding.field,
                "before": _json(finding.before),
                "after": _json(finding.after),
                "found_at": found_at,
            },
        )
    return findings


def _json(value: Any) -> str | None:
    return None if value is None else json.dumps(value)


def list_rewrites(
    engine: Engine,
    *,
    edition_id: uuid.UUID | None = None,
    theme: str | None = None,
    since: date | None = None,
    limit: int,
    offset: int,
) -> tuple[list[RewriteRecord], int]:
    """Findings, newest edition first and in the order the check found them within one. `since`
    is an as-of day: the editions of that day or later."""
    where = (
        " WHERE (CAST(:edition AS uuid) IS NULL OR r.edition_id = :edition)"
        " AND (CAST(:theme AS text) IS NULL OR e.theme = :theme)"
        " AND (CAST(:since AS date) IS NULL OR e.as_of >= :since)"
    )
    params: dict[str, Any] = {
        "edition": edition_id,
        "theme": theme,
        "since": since,
        "limit": limit,
        "offset": offset,
    }
    with engine.connect() as connection:
        total = connection.execute(
            text("SELECT count(*)" + _FROM + where),
            params,
        ).scalar_one()
        rows = connection.execute(
            text("SELECT " + _COLUMNS + _FROM + where + _ORDER + " LIMIT :limit OFFSET :offset"),
            params,
        ).all()
    return [RewriteRecord.model_validate(row, from_attributes=True) for row in rows], total
