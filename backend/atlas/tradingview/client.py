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
  v}]`. The answers' field names are not documented beyond the bars' keys: the calendar is
  assumed `{items: [{id?, symbol, title?, fiscal_period?, fiscal_year?, date (Unix s or
  ISO), status?}]}` and the bars `{bars: [...]}` or a bare list. An answer that doesn't
  fit fails the job with its first 4,000 characters in the artifacts (`UnexpectedAnswer`),
  so the lead can fit the shape from one live call. `tests/fixtures/tradingview/` are
  synthetic in these shapes.

Before each call, `before_call` (the jobs pass the cross-process cap, `service.RequestCap`)
runs: TradingView limits tool calls to about 100 a minute per user.
"""

from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any, cast

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from atlas.tradingview.mcp import McpClient, McpError, UnexpectedAnswer

DOCUMENTS_TOOL = "mcp-tv-get-documents"
DOCUMENT_VIEW_TOOL = "mcp-tv-get-document-view"
NEWS_TOOL = "mcp-tv-get-news"
# The proxy's earnings-calendar and daily-bars tools (the proxy names a tool `mcp-tv-` plus
# its TradingView name with hyphens); these constants are the one place the names change.
CALENDAR_TOOL = "mcp-tv-get-earnings-calendar"
OHLCV_TOOL = "mcp-tv-get-ohlcv"
MAX_BARS = 5000  # get_ohlcv's `count` ceiling

type CallRecorder = Callable[[str, str | None], None]


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


class CalendarItem(_Model):
    """One reporting date the earnings calendar lists (assumed field names; see the module).

    Only the date, the fiscal period and the status are taken: the model ignores every other
    field, so a consensus estimate in the answer (`eps_estimate`, `consensus`, ...) never
    reaches Atlas's records.
    """

    id: str | None = None
    symbol: str | None = None
    title: str | None = None
    fiscal_period: str | None = None
    fiscal_year: str | None = None
    date: datetime  # Unix seconds, an RFC 3339 time or a plain date (midnight UTC) in the answer
    status: str | None = None

    _as_text = field_validator("id", "fiscal_year", "fiscal_period", mode="before")(_text)

    @field_validator("date", mode="before")
    @classmethod
    def _as_moment(cls, value: Any) -> Any:
        if isinstance(value, int | float) and not isinstance(value, bool):
            return datetime.fromtimestamp(value, UTC)
        if isinstance(value, str):
            moment = datetime.fromisoformat(value)  # ValueError: a validation error
            return moment if moment.tzinfo else moment.replace(tzinfo=UTC)
        return value

    @property
    def event_at(self) -> datetime:
        return self.date


class CalendarList(_Model):
    items: list[CalendarItem] = []
    total: int | None = None


class Bar(_Model):
    """One daily bar, in the documented shape `{t (Unix s UTC), o, h, l, c, v}`; only the
    close is kept."""

    time: float = Field(validation_alias=AliasChoices("t", "time"))
    close: float = Field(validation_alias=AliasChoices("c", "close"))

    @property
    def at(self) -> datetime:
        return datetime.fromtimestamp(self.time, UTC)


class BarList(_Model):
    bars: list[Bar] = []

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
        before_call: Callable[[], None] = lambda: None,
    ) -> None:
        self._mcp = mcp
        self._max_calls = max_calls
        self._on_call = on_call
        self._before_call = before_call
        self.calls = 0

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
        (UTC), in one call. Only dates, period and status are kept of each (see the model)."""
        _, value = self._call(
            CALENDAR_TOOL,
            {
                "symbols": symbols,
                "date_from": _day(start),
                "date_to": _day(end),
            },
        )
        return _validate(CalendarList, value, CALENDAR_TOOL).items

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
