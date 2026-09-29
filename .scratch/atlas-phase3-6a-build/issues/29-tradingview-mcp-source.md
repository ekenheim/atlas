# 29: TradingView MCP as a source (evaluation, then adapter)

**What to build:** Decide whether, and how, Atlas uses the owner's TradingView subscription through TradingView's official MCP server (https://www.tradingview.com/mcp/docs). It needs the Essential plan or above, signs in with OAuth 2.1 (no API keys), and allows about 100 calls per minute per user. It exposes:
- OHLCV bars, quotes and economic indicators
- fundamentals and analyst consensus
- news headlines and full text
- a screener over 200+ metrics
- earnings, economic and dividend calendars

Candidate uses:
- news as Tier C leads (like SearXNG), or as Evidence where the story is primary
- the screener for discovery of unseeded companies
- earnings calendars for catalysts
- market data for Phase 6b and §8.2 market-implied expectations

Owner direction (2026-09-29): "we could most likely connect this to Atlas later … this seems important, we can get news etc from there."

**Blocked by:** None for the evaluation. The adapter waits on the evaluation, on ticket 08 (leads) and on ticket 27 (pacing).

**Status:** wontfix (for Atlas integration; interactive use only)

- [ ] Terms check, done the way the exchange check was: TradingView's Terms of Use and any MCP-specific terms on storage, archiving, redistribution, automated or server-side use, and AI use of news text. Also the licensing of exchange-sourced market data (often display-only). Quote and cite in `docs/decisions.md`.
- [ ] Feasibility of Atlas as an MCP client: OAuth 2.1 from a headless service (token refresh, storage as a secret), and the tool schemas.
- [ ] Decision per use (news, screener, calendars, market data): allowed, and with what source tier and `available_at` basis. News keeps the publisher, not TradingView, as the source where it names one.
- [ ] If allowed: an adapter ticket under the pacing budget, with fixtures from the documented tool schemas.

**Resolution (2026-09-30):** tested live in the owner's session; the terms check found automated server-side use, archiving and feeding Hindsight not allowed (display-only, no non-display use; Quartr's no-archive clause). The TradingView entry in `docs/decisions.md` has the quotes. No adapter will be built.
