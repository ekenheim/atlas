"""What every TradingView item shares: the provider, the job kinds, the override it records,
and the identifier URL of a transcript view's Source Document."""

from urllib.parse import quote

PROVIDER_ID = "tradingview"
CATALOG_KIND = "tradingview_catalog"
TRANSCRIPTS_KIND = "tradingview_transcripts"
# Recorded on every stored TradingView item and fetch observation (docs/decisions.md,
# "Owner override: TradingView as a source").
OWNER_OVERRIDE = (
    "TradingView terms (display-only) overridden by the owner for private non-commercial use"
    " (2026-09-30)"
)
# A transcript view's Source Document URL: an identifier Atlas builds (TradingView has no
# public URL for a view), stable per document and view.
TRANSCRIPT_BASE = "https://mcp.tradingview.com/documents"


def transcript_url(document_id: str, view_id: str) -> str:
    return f"{TRANSCRIPT_BASE}/{quote(document_id, safe='')}/views/{quote(view_id, safe='')}"
