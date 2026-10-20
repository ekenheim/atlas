"""The rewrite check (atlas-record ticket 02): what a later edition changed in an earlier one.

`compare_ledgers(ledger, previous)` is pure: it takes a ledger and the same theme's previous
parsed ledger and returns the differences that say a task rewrote what it had already said
(`Rewrite`). It never reads the store; `atlas.record.editions` runs it when an edition is stored
and records each finding insert-only in `ledger_rewrite`.

The kinds:

- `prediction_changed`: the `text`, `deadline`, `chokepoint` or `made` of a past prediction
  differs (one finding per field). A field the previous edition did not have is no change.
- `prediction_removed`: a prediction's ID is gone.
- `prediction_unsettled`: a prediction settled before is open again, or its settlement (`state`,
  `settled_on`, `settlement_quote`, `settlement_url`) changed. A prediction that was open and is
  now settled is the point of the record, never a finding.
- `chokepoint_vanished`: a chokepoint's ID is gone and the previous edition had not marked it
  `killed`. The council's board is a ranking, so an item that leaves it is no finding; an item
  on both boards is compared by its `chokepoint_id`.
- `id_reused`: an ID's `name` or `layer` (the board's `theme`) changed beyond wording. Two values
  equal after normalising case, punctuation and whitespace are the same; any other is reported
  for the reviewer to read.
- `date_moved_later`: `first_seen` or `earliest_evidence` (a board item's `earliest_evidence`,
  a contradiction's `first_seen`) moved later. Dates are read at the precision both give
  ("2026-07" then "2026-07-15" is no move); a value either edition did not write, or one that
  is not a date, is no finding.
- `edition_not_increasing`: the edition number did not rise.

A missing optional field (`earliest_evidence`, `consensus`, `council_answers`, `notes`) is never
a finding. Findings come in a fixed order (edition, chokepoints, predictions, then the council's
board and contradictions), so the same pair always gives the same list.
"""

import re
import unicodedata
from typing import Any, Literal

from pydantic import BaseModel, Field

from atlas.record.ledger import (
    CouncilLedger,
    Ledger,
    LedgerPrediction,
    ThemeLedger,
)

type RewriteKind = Literal[
    "prediction_changed",
    "prediction_removed",
    "prediction_unsettled",
    "chokepoint_vanished",
    "id_reused",
    "date_moved_later",
    "edition_not_increasing",
]

REWRITE_KINDS: tuple[RewriteKind, ...] = (
    "prediction_changed",
    "prediction_removed",
    "prediction_unsettled",
    "chokepoint_vanished",
    "id_reused",
    "date_moved_later",
    "edition_not_increasing",
)

_PREDICTION_FIELDS = ("text", "deadline", "chokepoint", "made")
_SETTLEMENT_FIELDS = ("state", "settled_on", "settlement_quote", "settlement_url")
_DATE = re.compile(r"^(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?")


class Rewrite(BaseModel):
    kind: RewriteKind
    subject_id: str = Field(
        description="the ID the finding is about (an edition's number: the theme's slug)"
    )
    field: str | None = Field(default=None, description="the field that differs, when one does")
    before: Any = Field(default=None, description="the previous edition's value")
    after: Any = Field(default=None, description="this edition's value; null when it is gone")


def normalise(value: str) -> str:
    """Case, punctuation and whitespace folded away: what two wordings of a name share."""
    folded = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(re.sub(r"[\W_]+", " ", folded).split())


def _date_parts(value: str) -> tuple[int, ...] | None:
    match = _DATE.match(value.strip())
    if match is None:
        return None
    return tuple(int(part) for part in match.groups() if part is not None)


def _moved_later(before: str | None, after: str | None) -> bool:
    if before is None or after is None:
        return False
    old, new = _date_parts(before), _date_parts(after)
    if old is None or new is None:
        return False
    width = min(len(old), len(new))
    return new[:width] > old[:width]


def _later(subject: str, field: str, before: str | None, after: str | None) -> list[Rewrite]:
    if not _moved_later(before, after):
        return []
    return [
        Rewrite(
            kind="date_moved_later", subject_id=subject, field=field, before=before, after=after
        )
    ]


def _reworded(subject: str, field: str, before: str | None, after: str | None) -> list[Rewrite]:
    if before is None or after is None or normalise(before) == normalise(after):
        return []
    return [Rewrite(kind="id_reused", subject_id=subject, field=field, before=before, after=after)]


def _settled(prediction: LedgerPrediction) -> bool:
    return prediction.state is not None and prediction.state.strip().casefold() != "open"


def _predictions(
    predictions: list[LedgerPrediction], previous: list[LedgerPrediction]
) -> list[Rewrite]:
    now = {p.id: p for p in predictions}
    found: list[Rewrite] = []
    for old in previous:
        new = now.get(old.id)
        if new is None:
            found.append(
                Rewrite(
                    kind="prediction_removed",
                    subject_id=old.id,
                    before=old.model_dump(mode="json"),
                )
            )
            continue
        for field in _PREDICTION_FIELDS:
            before, after = getattr(old, field), getattr(new, field)
            if before is not None and before != after:
                found.append(
                    Rewrite(
                        kind="prediction_changed",
                        subject_id=old.id,
                        field=field,
                        before=before,
                        after=after,
                    )
                )
        if _settled(old):
            before = {field: getattr(old, field) for field in _SETTLEMENT_FIELDS}
            after = {field: getattr(new, field) for field in _SETTLEMENT_FIELDS}
            if before != after:
                found.append(
                    Rewrite(
                        kind="prediction_unsettled", subject_id=old.id, before=before, after=after
                    )
                )
    return found


def _theme(ledger: ThemeLedger, previous: ThemeLedger) -> list[Rewrite]:
    found: list[Rewrite] = []
    now = {c.id: c for c in ledger.chokepoints}
    for old in previous.chokepoints:
        new = now.get(old.id)
        if new is None:
            if (old.status or "").strip().casefold() != "killed":
                found.append(
                    Rewrite(
                        kind="chokepoint_vanished",
                        subject_id=old.id,
                        before=old.model_dump(mode="json"),
                    )
                )
            continue
        found += _reworded(old.id, "name", old.name, new.name)
        found += _reworded(old.id, "layer", old.layer, new.layer)
        found += _later(old.id, "first_seen", old.first_seen, new.first_seen)
        found += _later(old.id, "earliest_evidence", old.earliest_evidence, new.earliest_evidence)
    return found + _predictions(ledger.predictions, previous.predictions)


def _text(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _council(ledger: CouncilLedger, previous: CouncilLedger) -> list[Rewrite]:
    found: list[Rewrite] = []
    board = {item.chokepoint_id: item for item in ledger.board}
    for old in previous.board:
        new = board.get(old.chokepoint_id)
        if new is None:
            # Leaving the top of the board is a re-ranking, not a rewrite.
            continue
        found += _reworded(old.chokepoint_id, "theme", old.theme, new.theme)
        found += _later(
            old.chokepoint_id, "earliest_evidence", old.earliest_evidence, new.earliest_evidence
        )
    found += _predictions(ledger.predictions, previous.predictions)
    now = {str(c["id"]): c for c in ledger.contradictions if "id" in c}
    for old_item in previous.contradictions:
        if "id" not in old_item:
            continue
        new_item = now.get(str(old_item["id"]))
        if new_item is not None:
            found += _later(
                str(old_item["id"]),
                "first_seen",
                _text(old_item.get("first_seen")),
                _text(new_item.get("first_seen")),
            )
    return found


def compare_ledgers(ledger: Ledger, previous: Ledger) -> list[Rewrite]:
    """The rewrites `ledger` makes of `previous`, the same theme's previous parsed edition."""
    found: list[Rewrite] = []
    if ledger.edition <= previous.edition:
        subject = ledger.theme if isinstance(ledger, ThemeLedger) else "council"
        found.append(
            Rewrite(
                kind="edition_not_increasing",
                subject_id=subject,
                field="edition",
                before=previous.edition,
                after=ledger.edition,
            )
        )
    if isinstance(ledger, ThemeLedger) and isinstance(previous, ThemeLedger):
        return found + _theme(ledger, previous)
    if isinstance(ledger, CouncilLedger) and isinstance(previous, CouncilLedger):
        return found + _council(ledger, previous)
    return found
