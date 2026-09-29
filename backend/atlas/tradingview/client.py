"""TradingView's tools Atlas uses, typed, bounded per job and recorded.

Only three tools are ever called (ticket 31's scope): `mcp-tv-get-documents` (the filing and
event catalog), `mcp-tv-get-document-view` (a transcript view's text) and `mcp-tv-get-news`
(headline metadata). Prices, fundamentals, the screener, alerts and watchlists are out of
scope, and no method here reaches them.

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
"""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from atlas.tradingview.mcp import McpClient, McpError

DOCUMENTS_TOOL = "mcp-tv-get-documents"
DOCUMENT_VIEW_TOOL = "mcp-tv-get-document-view"
NEWS_TOOL = "mcp-tv-get-news"

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


class _NewsData(_Model):
    headlines: list[Headline] = []


class _News(_Model):
    data: _NewsData = _NewsData()
    success: bool = True


class TradingViewClient:
    def __init__(self, mcp: McpClient, *, max_calls: int, on_call: CallRecorder) -> None:
        self._mcp = mcp
        self._max_calls = max_calls
        self._on_call = on_call
        self.calls = 0

    def _call(self, tool: str, arguments: dict[str, Any]) -> tuple[str, Any]:
        if self.calls >= self._max_calls:
            raise CallBoundReached(f"this job's {self._max_calls} TradingView calls are made")
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


def _rfc3339(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _validate[M: BaseModel](model: type[M], value: Any, tool: str) -> M:
    try:
        return model.model_validate(value)
    except ValidationError as error:
        raise McpError(f"{tool}: unexpected answer: {error.error_count()} problems") from None
