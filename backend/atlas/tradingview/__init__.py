"""TradingView as an owner-override source (ticket 31; off by default).

The owner uses their own TradingView subscription through TradingView's official MCP server
as a private, non-commercial proof of concept, knowingly overriding TradingView's
display-only terms (docs/decisions.md, "Owner override: TradingView as a source"). Scope:
transcripts (Tier B Source Versions), the filing catalog (metadata) and news-headline leads
(Tier C). Never prices, fundamentals, the screener, alerts or watchlists.

`tokens` holds the owner's OAuth tokens and refreshes them; `login` is `atlas tradingview
login`, the OAuth 2.1 authorization-code + PKCE flow; `mcp` the MCP client over streamable
HTTP; `client` the three tools Atlas calls, bounded and recorded; `service` the
`tradingview_catalog` and `tradingview_transcripts` jobs; `reads` the catalog's read side.
"""

from atlas.tradingview.client import CallBoundReached, TradingViewClient
from atlas.tradingview.mcp import McpClient, McpError, McpToolError, TradingViewUnavailable
from atlas.tradingview.model import (
    CATALOG_KIND,
    OWNER_OVERRIDE,
    PROVIDER_ID,
    TRANSCRIPTS_KIND,
    transcript_url,
)
from atlas.tradingview.reads import CatalogEntry, CatalogView, list_catalog
from atlas.tradingview.tokens import TokenSet, TokenStore, TradingViewAuthError, write_token_file

__all__ = [
    "CATALOG_KIND",
    "OWNER_OVERRIDE",
    "PROVIDER_ID",
    "TRANSCRIPTS_KIND",
    "CallBoundReached",
    "CatalogEntry",
    "CatalogView",
    "McpClient",
    "McpError",
    "McpToolError",
    "TokenSet",
    "TokenStore",
    "TradingViewAuthError",
    "TradingViewClient",
    "TradingViewUnavailable",
    "list_catalog",
    "transcript_url",
    "write_token_file",
]
