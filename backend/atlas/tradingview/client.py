"""TradingView's tools Atlas uses, typed, bounded per job and recorded.

Five tools are ever called: `mcp-tv-get-documents` (the filing and event catalog),
`mcp-tv-get-document-view` (a transcript view's text) and `mcp-tv-get-news` (headline
metadata) from ticket 31, and, from ticket 16b, the earnings calendar (`CALENDAR_TOOL`, for
Tier C leads) and daily price history (`OHLCV_TOOL`, for settling predictions and replays).
Fundamentals, consensus, the screener, alerts and watchlists are out of scope, and no method
here reaches them.

Each call is recorded (`on_call(tool, error)`, which the jobs write to `tradingview_request`
for the `tradingview` budget) whether it succeeded or not, and a client makes at most
`max_calls` calls: one more raises `CallBoundReached` before anything is sent.

Response shapes (TradingView's MCP answers, as described in docs/decisions.md; the
fixtures under `tests/fixtures/tradingview/` are synthetic):
- `get_documents` → `{items: [{category: {id, title}, correlation_id, event, fiscal_period?,
  fiscal_year, form?: {id, title}, id, provider: {id, name}, reported (Unix s), status,
  symbols: [{symbol}], title, views: [{id, type: transcript|summary|pdf}]}], total}`
- `get_document_view` (a view's `id`, verbatim) → `{astDescription: {type: "root",
  children: [...]}, id, provider: {id, name}, published (Unix s), title}`. PDF views aren't
  retrievable.
- `get_news` → `{data: {headlines: [{id, title, published, provider: {id, name, url?},
  link, storyPath, relatedSymbols: [{symbol}], urgency, paywall, permission}], has_more,
  next_offset, total_available}, success}`
- the earnings calendar and `get_ohlcv` (ticket 16c): the **arguments are as TradingView
  documents them** (https://www.tradingview.com/mcp/docs, read 2026-10-15; the proxy names
  a tool `mcp-tv-` plus its name with hyphens). `get_earnings_calendar` takes `symbols[]`
  (required, `EXCHANGE:TICKER`), `date_from` (default today) and `date_to` (default +180
  days), as `YYYY-MM-DD` or RFC 3339, and answers only the next scheduled and the most
  recent report date of each symbol, plus consensus estimates, which Atlas takes out of
  the answer before anything is kept. `get_ohlcv` takes `symbol`, `interval` (default `1D`),
  `count` (default 300, at most 5000, counted back from now: there is no date range) and
  `summary`, and answers an aggregate summary and the bars `[{t (Unix s UTC), o, h, l, c,
  v}]`. The calendar's answer shape was confirmed on 2026-10-16 from the first live call
  (ticket 16d): `{success, data: {count, from, to, earnings: [{symbol, fiscal_period_end,
  release_date, release_next_date, next_date_confirmed, ...}]}}`, one row per symbol listed
  (a symbol with no data is absent), each row holding two events: the next report and the
  most recent one (see `CalendarItem`); `fiscal_period_end` is the quarter the **next**
  report is for. A row also carries a price, a name, a description, flags and consensus
  estimates, which the model never names and Atlas never keeps. `data.earnings` is required
  (another wrapper key fails the job, never an empty calendar). The bars are assumed
  `{bars: [...]}` or a bare list, and `bars` is required too. An answer that doesn't fit
  fails the job with its first 4,000 characters in the artifacts (`UnexpectedAnswer`), so
  the lead can fit a shape from one live call. `tests/fixtures/tradingview/` are synthetic
  in these shapes.

Before each call, `before_call` (the jobs pass the cross-process cap, `service.RequestCap`)
runs: TradingView limits tool calls to about 100 a minute per user.
"""

import calendar
import re
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal, cast

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from atlas.tradingview.mcp import CALENDAR_TOOL, McpClient, McpError, UnexpectedAnswer

DOCUMENTS_TOOL = "mcp-tv-get-documents"
DOCUMENT_VIEW_TOOL = "mcp-tv-get-document-view"
NEWS_TOOL = "mcp-tv-get-news"
# The proxy's earnings-calendar and daily-bars tools (the proxy names a tool `mcp-tv-` plus
# its TradingView name with hyphens); these constants are the one place the names change.
OHLCV_TOOL = "mcp-tv-get-ohlcv"
MAX_BARS = 5000  # get_ohlcv's `count` ceiling

type CallRecorder = Callable[[str, str | None], None]

_ISO_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")


class CallBoundReached(Exception):
    """This job has made all the TradingView calls it may."""


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, populate_by_name=True)


def _text(value: Any) -> Any:
    """IDs and years arrive as strings or numbers; Atlas keeps them as text."""
    return str(value) if isinstance(value, int | float) and not isinstance(value, bool) else value


def _time(value: int | float | None) -> datetime | None:
    return None if value is None else datetime.fromtimestamp(value, UTC)


class Named(_Model):
    id: str | None = None
    title: str | None = None
    name: str | None = None
    url: str | None = None

    _as_text = field_validator("id", mode="before")(_text)


class View(_Model):
    id: str
    type: str

    _as_text = field_validator("id", mode="before")(_text)


class Symbol(_Model):
    symbol: str


class Document(_Model):
    id: str
    title: str = ""
    category: Named | None = None
    correlation_id: str | None = None
    event: str | None = None
    fiscal_period: str | None = None
    fiscal_year: str | None = None
    form: Named | None = None
    provider: Named | None = None
    reported: float | None = None
    status: str | None = None
    symbols: list[Symbol] = []
    views: list[View] = []

    _as_text = field_validator(
        "id", "correlation_id", "fiscal_year", "fiscal_period", mode="before"
    )(_text)

    @property
    def reported_at(self) -> datetime | None:
        return _time(self.reported)

    def transcript_views(self) -> list[View]:
        return [view for view in self.views if view.type == "transcript"]


class DocumentList(_Model):
    items: list[Document] = []
    total: int | None = None


class DocumentView(_Model):
    id: str
    title: str = ""
    provider: Named | None = None
    published: float | None = None

    _as_text = field_validator("id", mode="before")(_text)

    @property
    def published_at(self) -> datetime | None:
        return _time(self.published)


class Headline(_Model):
    id: str
    title: str
    published: float | None = None
    provider: Named | None = None
    link: str | None = None
    story_path: str | None = Field(default=None, alias="storyPath")
    related_symbols: list[Symbol] = Field(default=[], alias="relatedSymbols")
    urgency: int | None = None

    _as_text = field_validator("id", mode="before")(_text)

    @property
    def published_at(self) -> datetime | None:
        return _time(self.published)


type CalendarStatus = Literal["reported", "scheduled", "confirmed"]
type PeriodBasis = Literal["stated", "derived_from_next"]


class CalendarItem(_Model):
    """One reporting date of the earnings calendar (ticket 16d): a row of TradingView's answer
    holds up to two, the next report and the most recent one.

    - the **next** report: `release_next_date`, `confirmed` when `next_date_confirmed` is
      true, else `scheduled`, for the quarter ending `fiscal_period_end` (`stated`);
    - the **most recent** report: `release_date`, `reported`, for the quarter ending three
      months before `fiscal_period_end` (the month end three months earlier; `derived_from_next`,
      TradingView says nothing of that quarter), so that when a scheduled report happens the
      next answer names it as the recent one with the same period end: the same event.

    An event is identified by the symbol and its period's end day. Nothing else of a row is
    kept (the model has no field for it): not its price, name, description or flags, and no
    consensus or estimate."""

    symbol: str
    period_end: date
    on: date  # the reporting day
    status: CalendarStatus
    period_basis: PeriodBasis

    @property
    def event_at(self) -> datetime:
        return datetime(self.on.year, self.on.month, self.on.day, tzinfo=UTC)


class _EarningsRow(_Model):
    """The fields of an answer's row Atlas names; every other key is ignored, and a date that
    is missing or isn't a date skips its event (`_events`) instead of failing the answer."""

    symbol: str
    fiscal_period_end: Any = None
    release_date: Any = None
    release_next_date: Any = None
    next_date_confirmed: bool | None = None


class _EarningsData(_Model):
    earnings: list[_EarningsRow]  # required: another wrapper key is not an empty calendar


class CalendarList(_Model):
    success: bool = True
    data: _EarningsData


def _day_of(value: Any) -> date | None:
    """The day an answer's date names: `2026-08-11`, or an ISO time (the date as written: its
    first ten characters, whatever the time and offset after them)."""
    if not isinstance(value, str) or not _ISO_DAY.match(value):
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


SNAP_DAYS = 7


def _snap_to_month_end(day: date) -> date:
    """`day`, or the month end it is within `SNAP_DAYS` of: a 52/53-week fiscal quarter ends on a
    weekday near a month end (26 Sep), which the quarters of other answers name by the month
    end (30 Sep). Any other date is left as it is."""
    this_end = date(day.year, day.month, calendar.monthrange(day.year, day.month)[1])
    previous_end = day.replace(day=1) - timedelta(days=1)
    nearest = min((this_end, previous_end), key=lambda end: abs((end - day).days))
    return nearest if abs((nearest - day).days) <= SNAP_DAYS else day


def _month_end_before(day: date, months: int) -> date:
    """The last day of the month `months` before the one `day` is in."""
    index = day.year * 12 + day.month - 1 - months
    year, month = divmod(index, 12)
    return date(year, month + 1, calendar.monthrange(year, month + 1)[1])


def _events(row: _EarningsRow) -> tuple[list[CalendarItem], int]:
    """A row's events and how many it could not make (the answer gave no usable date). With no
    usable `fiscal_period_end` neither event has a period to be identified by."""
    period_end = _day_of(row.fiscal_period_end)
    if period_end is not None:
        period_end = _snap_to_month_end(period_end)
    next_on, recent_on = _day_of(row.release_next_date), _day_of(row.release_date)
    if period_end is None:
        return [], 2
    items: list[CalendarItem] = []
    if next_on is not None:
        items.append(
            CalendarItem(
                symbol=row.symbol,
                period_end=period_end,
                on=next_on,
                status="confirmed" if row.next_date_confirmed else "scheduled",
                period_basis="stated",
            )
        )
    if recent_on is not None:
        items.append(
            CalendarItem(
                symbol=row.symbol,
                period_end=_month_end_before(period_end, 3),
                on=recent_on,
                status="reported",
                period_basis="derived_from_next",
            )
        )
    return items, 2 - len(items)


class Bar(_Model):
    """One daily bar, in the documented shape `{t (Unix s UTC), o, h, l, c, v}`; only the
    close is kept. The day is taken from `t` in UTC: unconfirmed for a non-US exchange (a bar
    stamped at local midnight would land a day early); see docs/decisions.md."""

    time: float = Field(validation_alias=AliasChoices("t", "time"))
    close: float = Field(validation_alias=AliasChoices("c", "close"))

    @property
    def at(self) -> datetime:
        return datetime.fromtimestamp(self.time, UTC)


class BarList(_Model):
    bars: list[Bar]  # required, as above; a bare list is wrapped by the validator

    @model_validator(mode="before")
    @classmethod
    def _bare_list(cls, value: Any) -> Any:
        if isinstance(value, list):
            return {"bars": cast(list[Any], value)}
        return value


def trading_days_back(start: date, today: date) -> int:
    """How many daily bars back from `today` reach `start`: the weekdays from one to the
    other, inclusive. Holidays make the true number smaller, so the start is never missed."""
    if start > today:
        return 1
    days = (today - start).days + 1
    weeks, extra = divmod(days, 7)
    weekdays = weeks * 5 + sum(
        1 for offset in range(extra) if (start + timedelta(days=weeks * 7 + offset)).weekday() < 5
    )
    return max(weekdays, 1)


class _NewsData(_Model):
    headlines: list[Headline] = []


class _News(_Model):
    data: _NewsData = _NewsData()
    success: bool = True


class TradingViewClient:
    def __init__(
        self,
        mcp: McpClient,
        *,
        max_calls: int,
        on_call: CallRecorder,
        before_call: Callable[[], None],
    ) -> None:
        self._mcp = mcp
        self._max_calls = max_calls
        self._on_call = on_call
        self._before_call = before_call
        self.calls = 0
        self.calendar_events_skipped = 0  # events the calendar's answers gave no date for

    def _call(self, tool: str, arguments: dict[str, Any]) -> tuple[str, Any]:
        if self.calls >= self._max_calls:
            raise CallBoundReached(f"this job's {self._max_calls} TradingView calls are made")
        self._before_call()  # may wait: TradingView's calls a minute are limited
        self.calls += 1
        try:
            result = self._mcp.call_tool(tool, arguments)
        except Exception as error:
            self._on_call(tool, f"{type(error).__name__}: {error}")
            raise
        self._on_call(tool, None)
        return result.text, result.value

    def documents(self, symbol: str, *, start: datetime, end: datetime, limit: int) -> DocumentList:
        _, value = self._call(
            DOCUMENTS_TOOL,
            {
                "symbol": symbol,
                "start_date": _rfc3339(start),
                "end_date": _rfc3339(end),
                "limit": limit,
            },
        )
        return _validate(DocumentList, value, DOCUMENTS_TOOL)

    def document_view(self, view_id: str) -> tuple[str, DocumentView]:
        """The view's answer exactly as received (what the ledger archives), and parsed."""
        text, value = self._call(DOCUMENT_VIEW_TOOL, {"view_id": view_id})
        return text, _validate(DocumentView, value, DOCUMENT_VIEW_TOOL)

    def news(self, symbol: str, *, lang: str, limit: int) -> list[Headline]:
        _, value = self._call(
            NEWS_TOOL, {"symbol": symbol, "lang": lang, "limit": limit, "offset": 0}
        )
        news = _validate(_News, value, NEWS_TOOL)
        if not news.success:
            raise McpError(f"{NEWS_TOOL}: the answer says it didn't succeed")
        return news.data.headlines

    def calendar(self, symbols: list[str], *, start: datetime, end: datetime) -> list[CalendarItem]:
        """The reporting dates of all `symbols` between the days `start` and `end` fall on
        (UTC), in one call: up to two events a symbol the answer lists (see `CalendarItem`).
        A symbol the answer leaves out is no error; an event with no usable date is skipped
        and counted in `calendar_events_skipped`."""
        _, value = self._call(
            CALENDAR_TOOL,
            {
                "symbols": symbols,
                "date_from": _day(start),
                "date_to": _day(end),
            },
        )
        answer = _validate(CalendarList, value, CALENDAR_TOOL)
        if not answer.success:
            raise UnexpectedAnswer(CALENDAR_TOOL, "the answer says it didn't succeed", value)
        rows = answer.data.earnings
        asked = set(symbols)
        if rows and not any(row.symbol in asked for row in rows):
            # Every row names a symbol Atlas didn't ask for (another form: `LITE`, lower case):
            # the job would succeed with nothing listed, which looks like an empty calendar.
            raise UnexpectedAnswer(CALENDAR_TOOL, "no row names a symbol asked for", value)
        items: list[CalendarItem] = []
        for row in rows:
            made, skipped = _events(row)
            items += made
            self.calendar_events_skipped += skipped
        return items

    def daily_bars(self, symbol: str, *, start: date, end: date, today: date) -> list[Bar]:
        """The daily bars from `start` to `end` inclusive (UTC days). The tool counts back
        from now and has no date range, so Atlas asks for as many bars as reach `start` from
        `today` (at most `MAX_BARS`) and keeps the ones inside the window."""
        _, value = self._call(
            OHLCV_TOOL,
            {
                "symbol": symbol,
                "interval": "1D",
                "count": min(trading_days_back(start, today), MAX_BARS),
            },
        )
        bars = _validate(BarList, value, OHLCV_TOOL).bars
        return [bar for bar in bars if start <= bar.at.date() <= end]


def _rfc3339(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _day(moment: datetime) -> str:
    return moment.astimezone(UTC).date().isoformat()


def _validate[M: BaseModel](model: type[M], value: Any, tool: str) -> M:
    try:
        return model.model_validate(value)
    except ValidationError as error:
        raise UnexpectedAnswer(tool, f"{error.error_count()} problems", value) from None
