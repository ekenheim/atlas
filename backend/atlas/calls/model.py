"""What a call is, as the API shows it (atlas-beliefs ticket 19): the dated record of what Atlas
said, with the checkpoints that followed. Also the pure parts of settling one: the horizons,
the due dates and the arithmetic of a checkpoint."""

import calendar
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Literal

from pydantic import BaseModel

type Origin = Literal["belief", "hypothesis", "signal"]
type Direction = Literal["tightening", "easing"]
type CallState = Literal["open", "settled", "unpriced"]
type UnpricedReason = Literal["no_symbol", "tradingview_disabled"]

HORIZONS: tuple[int, ...] = (1, 3, 6)  # months after the call
# A close counts as "the close on a day" when it is that day's or the last one before it, at
# most this many days back (a long weekend and a holiday; not a halted or delisted stock).
MAX_STALE_DAYS = 7

NOTE = (
    "What Atlas said, on the date it said it, and what followed. Closes are used only to score"
    " a call after the fact; they are never evidence for one."
)

# The direction a Belief's step carries: the constraint tightening, or easing. Other steps
# (control, capture) say nothing about it.
STEP_DIRECTION: Mapping[str, Direction] = {
    "constraint": "tightening",
    "demand_vs_supply": "tightening",
    "relief": "easing",
    "invalidation": "easing",
}


def step_direction(step: str) -> Direction | None:
    return STEP_DIRECTION.get(step)


def add_months(day: date, months: int) -> date:
    """`day` plus calendar months; a day the month lacks becomes the month's last (31 Jan + 1 =
    28 or 29 Feb)."""
    index = day.year * 12 + (day.month - 1) + months
    year, month = divmod(index, 12)
    month += 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def due_on(made_at: datetime, months: int) -> date:
    """The day a checkpoint falls due: the call's UTC date plus `months`."""
    return add_months(made_at.astimezone(UTC).date(), months)


@dataclass(frozen=True)
class Close:
    day: date
    close: float


def close_on_or_before(closes: Sequence[Close], day: date) -> Close | None:
    """The last close on `day` or before it, no more than `MAX_STALE_DAYS` back (missing days
    take the last close)."""
    best: Close | None = None
    for each in closes:
        if each.day <= day and (best is None or each.day > best.day):
            best = each
    if best is None or (day - best.day) > timedelta(days=MAX_STALE_DAYS):
        return None
    return best


@dataclass(frozen=True)
class Move:
    """One company's change over a checkpoint's window: the close on the call date and the one
    on the due day (each with the day it is from)."""

    key: str  # the company's slug
    symbol: str
    base_day: date
    base_close: float
    day: date
    close: float

    @property
    def change(self) -> float:
        return self.close / self.base_close - 1


def move(key: str, symbol: str, closes: Sequence[Close], made_on: date, due: date) -> Move | None:
    """The company's move from the call date to the due day, None if either close is missing
    or zero."""
    base = close_on_or_before(closes, made_on)
    end = close_on_or_before(closes, due)
    if base is None or end is None or base.close <= 0:
        return None
    return Move(key, symbol, base.day, base.close, end.day, end.close)


@dataclass(frozen=True)
class Outcome:
    change: float
    benchmark_change: float | None
    relative_change: float | None
    companies: list[Move]
    benchmark: list[Move]


def mean_change(moves: Sequence[Move]) -> float:
    return sum(each.change for each in moves) / len(moves)


def outcome(companies: Sequence[Move], benchmark: Sequence[Move]) -> Outcome | None:
    """A checkpoint from the call companies' moves and the benchmark members': the equal-weighted
    change of each, rounded to six places, and the difference. None when no company of the call
    has a move; a benchmark with no member leaves the benchmark and the difference empty."""
    if not companies:
        return None
    change = round(mean_change(companies), 6)
    if not benchmark:
        return Outcome(change, None, None, list(companies), [])
    bench = round(mean_change(benchmark), 6)
    return Outcome(change, bench, round(change - bench, 6), list(companies), list(benchmark))


# --- the read side --------------------------------------------------------------------------


class CallCompany(BaseModel):
    company_id: uuid.UUID
    slug: str
    display_name: str
    symbol: str | None


class CheckpointMove(BaseModel):
    company: str  # slug
    symbol: str
    base_day: date
    base_close: float
    day: date
    close: float
    change: float


class Checkpoint(BaseModel):
    horizon_months: int
    due_on: date
    change: float
    benchmark_change: float | None
    relative_change: float | None
    benchmark_members: int
    companies: list[CheckpointMove]
    benchmark: list[CheckpointMove]
    settled_at: datetime


class NextDue(BaseModel):
    horizon_months: int
    due_on: date


class Call(BaseModel):
    id: uuid.UUID
    origin: Origin
    origin_id: uuid.UUID
    lead_id: uuid.UUID | None
    theme: str
    claim: str
    direction: Direction | None
    made_at: datetime
    state: CallState
    unpriced_reason: UnpricedReason | None
    companies: list[CallCompany]
    checkpoints: list[Checkpoint]
    next_due: NextDue | None
    note: str = NOTE
