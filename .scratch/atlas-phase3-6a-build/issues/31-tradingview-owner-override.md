# 31: TradingView MCP source (owner override, off by default)

**What to build:** Atlas can use the owner's TradingView subscription as a source through TradingView's official MCP server (https://mcp.tradingview.com/mcp, OAuth 2.1), as an explicit **owner override** of TradingView's display-only terms. The owner decided this on 2026-09-30 for a private, non-commercial proof of concept, after the terms check recorded in `docs/decisions.md`. Scope:
- **Transcripts:** earnings-call and conference transcripts, from `get_documents` plus the `get_document_view` transcript views, become Source Versions. They are Tier B, with provider `tradingview`, the upstream provider (Quartr) recorded, `available_at` = the event's `reported` time (basis `publisher_timestamp`), and the text archived and parsed. Claims and Assertions work on them like any other source.
- **Filing catalog:** `get_documents` metadata (category, form, fiscal period, reported time, title) is stored as a catalog. It tells the owner and investigations which primary filings exist, which is useful where no adapter exists (for example, which Innolight reports to download for manual import). Summaries are never stored as evidence.
- **News leads:** `get_news` headline metadata (title, original publisher, published time, TradingView link, related symbols) becomes Tier C leads, joining discovery like SearXNG results. Story text isn't stored.
- **Out of scope:** prices, fundamentals, the screener, alerts and watchlists.

**Blocked by:** None

**Status:** paused (owner, 2026-09-30): resume the TradingView live check when deploying it to k8s

- [x] `ATLAS_TRADINGVIEW_ENABLED` (default **false**). While off, nothing calls TradingView. Every stored item and fetch observation records `owner_override: TradingView terms (display-only) overridden by the owner for private non-commercial use (2026-09-30)`.
- [x] An MCP client over HTTP (JSON-RPC, streamable HTTP) with an OAuth 2.1 token supplied by the owner. The access and refresh tokens come from settings or secrets and are never logged. Refresh is supported, and a missing or expired token is a clear error. It is tested at the transport against a scripted fake MCP server; there are no live calls in tests.
- [x] Gentle pacing: a fixed low rate (≤ 1 request/s, far under ~100/min), counted in the `minimax`-style budget view as its own provider `tradingview` (ticket 27's budget module), and bounded per job.
- [x] Jobs: `tradingview_catalog` (per company symbol: documents and news metadata) and `tradingview_transcripts` (fetch the transcripts selected by the catalog, within the lookback). Companies map to TradingView symbols through config (e.g. `NASDAQ:LITE`, `HKEX:3308`).
- [x] Fixtures are synthetic only and marked as such. No real TradingView, Quartr or news content is ever committed.
- [x] Docs: the decision entry records the owner's override and its scope; the runbook covers obtaining the OAuth token and turning the source on and off.
- [x] (Added by the lead, 2026-09-30, after the owner cleared live use) `atlas tradingview login`: Atlas's own OAuth token via the MCP authorization spec (protected-resource metadata, dynamic client registration, authorization code + PKCE, loopback redirect), stored in a gitignored 0600 token file or printed for secrets, refreshed automatically, tested against a scripted fake authorization server; `atlas tradingview check --symbol NASDAQ:LITE` makes one catalog call and prints counts only.
