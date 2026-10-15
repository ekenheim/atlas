"""What every TradingView item shares: the provider, the job kinds, the override it records,
and the identifier URL of a transcript view's Source Document."""

from urllib.parse import quote

PROVIDER_ID = "tradingview"
CATALOG_KIND = "tradingview_catalog"
TRANSCRIPTS_KIND = "tradingview_transcripts"
CALENDAR_KIND = "tradingview_calendar"
PRICES_KIND = "tradingview_prices"
# Recorded on every stored TradingView item and fetch observation (docs/decisions.md,
# "Owner override: TradingView as a source").
OWNER_OVERRIDE = (
    "TradingView terms (display-only) overridden by the owner for private non-commercial use"
    " (2026-09-30)"
)
# A transcript view's Source Document URL: an identifier Atlas builds (TradingView has no
# public URL for a view), stable per document and view.
TRANSCRIPT_BASE = "https://mcp.tradingview.com/documents"


CALENDAR_BASE = "https://mcp.tradingview.com/calendar"


def calendar_url(symbol: str, event_key: str) -> str:
    """A calendar lead's URL: an identifier Atlas builds (the calendar has no public page),
    stable per symbol and event, so a date that moves updates the same lead."""
    return f"{CALENDAR_BASE}/{quote(symbol, safe='')}/{quote(event_key, safe='')}"


def transcript_url(document_id: str, view_id: str) -> str:
    return f"{TRANSCRIPT_BASE}/{quote(document_id, safe='')}/views/{quote(view_id, safe='')}"
