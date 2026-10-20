"""The prediction record (atlas-record ticket 05): what each edition predicted, and how it fell.

`record_predictions` runs in the transaction that stores an edition (`Editions.import_page`):
each prediction ID of that ledger not seen before for the theme (the council's is `council`)
becomes one insert-only `ledger_prediction` row, as the ledger wrote it, audited
`ledger_prediction.recorded`. A later edition never changes the row; a difference is ticket 02's
finding. An edition whose prediction carries `state` `met` or `missed` with a `settled_on` day
gives it one insert-only `ledger_prediction_settlement` row the first time (audited
`ledger_prediction.settled`); a later, different settlement is not stored here (ticket 02 finds
`prediction_unsettled` and the like). Anything else the ledger says in `state` (`open`, a
`lapsed` the task wrote itself) settles nothing: Atlas derives lapse from the deadline.

The state is derived on read, never stored: `met` or `missed` from the settlement, else `lapsed`
when the deadline day has passed (the deadline day itself is still open, as for a Hypothesis's
prediction), else `open`. A deadline the task wrote that does not read as a day (`2027-02-28`, or
a month, `2027-03`, taken as its last day) has no `deadline_on`: it never lapses and is not due.
"""

import calendar
import re
import uuid
from datetime import UTC, date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import Connection, Engine, text

from atlas.audit import Actor, content_hash, record
from atlas.record.ledger import Ledger

type LedgerPredictionState = Literal["open", "lapsed", "met", "missed"]

_DAY = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_MONTH = re.compile(r"^(\d{4})-(\d{2})$")
_SETTLED: tuple[str | None, ...] = ("met", "missed")


def deadline_day(deadline: str | None) -> date | None:
    """The deadline as a day: `2027-02-28` as is, `2027-03` as its last day, else None."""
    if deadline is None:
        return None
    written = deadline.strip()
    try:
        if match := _DAY.match(written):
            return date(int(match[1]), int(match[2]), int(match[3]))
        if match := _MONTH.match(written):
            year, month = int(match[1]), int(match[2])
            return date(year, month, calendar.monthrange(year, month)[1])
    except ValueError:
        return None
    return None


def record_predictions(
    connection: Connection,
    actor: Actor,
    edition_id: uuid.UUID,
    theme: str,
    ledger: Ledger,
    recorded_at: datetime,
) -> tuple[int, int]:
    """Record the ledger's new predictions and first settlements: (predictions, settlements)."""
    recorded = settled = 0
    for each in ledger.predictions:
        if not each.id.strip() or not each.text.strip():
            continue
        row_id = uuid.uuid4()
        inserted = connection.execute(
            text(
                "INSERT INTO ledger_prediction (id, theme, prediction_id, chokepoint, made,"
                " deadline, deadline_on, text, source_type, edition_id, recorded_at)"
                " VALUES (:id, :theme, :prediction, :chokepoint, :made, :deadline, :deadline_on,"
                " :text, :source_type, :edition, :recorded_at)"
                " ON CONFLICT (theme, prediction_id) DO NOTHING RETURNING id"
            ),
            {
                "id": row_id,
                "theme": theme,
                "prediction": each.id,
                "chokepoint": each.chokepoint,
                "made": each.made,
                "deadline": each.deadline,
                "deadline_on": deadline_day(each.deadline),
                "text": each.text,
                "source_type": each.source_type,
                "edition": edition_id,
                "recorded_at": recorded_at,
            },
        ).scalar_one_or_none()
        if inserted is not None:
            recorded += 1
            record(
                connection,
                actor,
                "ledger_prediction.recorded",
                entity_type="ledger_prediction",
                entity_id=str(row_id),
                new_hash=content_hash(
                    {
                        "theme": theme,
                        "prediction": each.id,
                        "chokepoint": each.chokepoint,
                        "made": each.made,
                        "deadline": each.deadline,
                        "text": each.text,
                        "source_type": each.source_type,
                        "edition": edition_id,
                    }
                ),
            )
        settled_on = (each.settled_on or "").strip()
        if each.state not in _SETTLED or not settled_on:
            continue
        settlement_id = uuid.uuid4()
        prediction_row = connection.execute(
            text(
                "INSERT INTO ledger_prediction_settlement (id, prediction_id, edition_id, state,"
                " settled_on, quote, url, recorded_at)"
                " SELECT :id, p.id, :edition, :state, :settled_on, :quote, :url, :recorded_at"
                " FROM ledger_prediction p WHERE p.theme = :theme AND p.prediction_id = :prediction"
                " ON CONFLICT (prediction_id) DO NOTHING RETURNING prediction_id"
            ),
            {
                "id": settlement_id,
                "edition": edition_id,
                "state": each.state,
                "settled_on": settled_on,
                "quote": each.settlement_quote,
                "url": each.settlement_url,
                "recorded_at": recorded_at,
                "theme": theme,
                "prediction": each.id,
            },
        ).scalar_one_or_none()
        if prediction_row is not None:
            settled += 1
            record(
                connection,
                actor,
                "ledger_prediction.settled",
                entity_type="ledger_prediction",
                entity_id=str(prediction_row),
                new_hash=content_hash(
                    {
                        "settlement": settlement_id,
                        "state": each.state,
                        "settled_on": settled_on,
                        "quote": each.settlement_quote,
                        "url": each.settlement_url,
                        "edition": edition_id,
                    }
                ),
            )
    return recorded, settled


class RecordedSettlement(BaseModel):
    state: Literal["met", "missed"]
    settled_on: str = Field(description="the day the edition says it settled, as it wrote it")
    quote: str | None = Field(description="the settlement quote, as the edition wrote it")
    url: str | None
    edition_id: uuid.UUID = Field(description="the first edition that carried the settlement")
    recorded_at: datetime


class RecordedPrediction(BaseModel):
    id: uuid.UUID
    theme: str = Field(description="the theme's slug; `council` for the council's")
    prediction_id: str = Field(description="the ledger's ID, such as `pho-p1`")
    chokepoint: str | None = Field(description="the chokepoint's ID; the council's name none")
    made: str | None = Field(description="the day made, as the ledger wrote it")
    deadline: str | None = Field(description="the deadline, as the ledger wrote it")
    deadline_on: date | None = Field(
        description="the deadline as a day (a month is its last day); null when it reads as none:"
        " such a prediction never lapses"
    )
    text: str
    source_type: str | None
    edition_id: uuid.UUID = Field(description="the edition that first named it")
    state: LedgerPredictionState = Field(
        description="open before the deadline; lapsed after it with no settlement; met or missed"
        " once an edition settled it. Derived on every read."
    )
    settlement: RecordedSettlement | None
    recorded_at: datetime


_SELECT = """
SELECT p.id, p.theme, p.prediction_id, p.chokepoint, p.made, p.deadline, p.deadline_on, p.text,
       p.source_type, p.edition_id, p.recorded_at,
       s.state AS s_state, s.settled_on, s.quote, s.url, s.edition_id AS s_edition,
       s.recorded_at AS s_recorded
FROM ledger_prediction p
LEFT JOIN ledger_prediction_settlement s ON s.prediction_id = p.id
"""
_STATE = (
    "CASE WHEN s.id IS NOT NULL THEN s.state"
    " WHEN p.deadline_on < :today THEN 'lapsed' ELSE 'open' END"
)


def _shape(row: Any, today: date) -> RecordedPrediction:
    settlement = None
    if row.s_state is not None:
        settlement = RecordedSettlement(
            state=row.s_state,
            settled_on=row.settled_on,
            quote=row.quote,
            url=row.url,
            edition_id=row.s_edition,
            recorded_at=row.s_recorded,
        )
    state: LedgerPredictionState = (
        settlement.state
        if settlement
        else "lapsed"
        if row.deadline_on is not None and row.deadline_on < today
        else "open"
    )
    return RecordedPrediction(
        id=row.id,
        theme=row.theme,
        prediction_id=row.prediction_id,
        chokepoint=row.chokepoint,
        made=row.made,
        deadline=row.deadline,
        deadline_on=row.deadline_on,
        text=row.text,
        source_type=row.source_type,
        edition_id=row.edition_id,
        state=state,
        settlement=settlement,
        recorded_at=row.recorded_at,
    )


def today_of(now: datetime) -> date:
    return now.astimezone(UTC).date()


def list_ledger_predictions(
    engine: Engine,
    today: date,
    *,
    state: LedgerPredictionState | None,
    theme: str | None,
    due_before: date | None,
    limit: int,
    offset: int,
) -> tuple[list[RecordedPrediction], int]:
    """The recorded predictions, soonest deadline first (those with no deadline day last).
    `due_before` keeps those whose deadline day is on or before it."""
    where = (
        " WHERE (CAST(:theme AS text) IS NULL OR p.theme = :theme)"
        " AND (CAST(:due_before AS date) IS NULL OR p.deadline_on <= :due_before)"
        " AND (CAST(:state AS text) IS NULL OR " + _STATE + " = :state)"
    )
    params: dict[str, Any] = {
        "theme": theme,
        "due_before": due_before,
        "state": state,
        "today": today,
    }
    with engine.connect() as connection:
        total = connection.execute(
            text(
                "SELECT count(*) FROM ledger_prediction p"  # noqa: S608 (constant fragments)
                " LEFT JOIN ledger_prediction_settlement s ON s.prediction_id = p.id" + where
            ),
            params,
        ).scalar_one()
        rows = connection.execute(
            text(
                _SELECT + where + " ORDER BY p.deadline_on NULLS LAST, p.theme, p.prediction_id"
                " LIMIT :limit OFFSET :offset"
            ),
            params | {"limit": limit, "offset": offset},
        ).all()
    return [_shape(row, today) for row in rows], total


def get_ledger_prediction(
    engine: Engine, prediction_id: uuid.UUID, today: date
) -> RecordedPrediction | None:
    with engine.connect() as connection:
        row = connection.execute(
            text(_SELECT + " WHERE p.id = :id"), {"id": prediction_id}
        ).one_or_none()
    return None if row is None else _shape(row, today)
