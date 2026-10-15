# 16c: TradingView calls as documented, under one rate cap

Type: build
Status: ready-for-agent
Blocked by: none

## Why

TradingView's MCP documentation (https://www.tradingview.com/mcp/docs, read 2026-10-15) contradicts the shapes ticket 16b assumed, and states a limit Atlas could exceed:
- "Tool calls are rate-limited to ~100 requests per minute per user." The owner's own use shares it. Atlas paces per process (`tradingview_rate_per_s`, 0.5/s, an in-process token bucket), so three workers and the API together could reach about 120 calls a minute.
- `get_earnings_calendar`: args `symbols[]` (required), `date_from` (default today), `date_to` (default +180 days). It returns only the next scheduled and the most recent report dates per symbol, not history, plus consensus estimates (which Atlas must not store: the owner disallowed consensus on 2026-10-15). Atlas sends `symbol`, `start_date`, `end_date`.
- `get_ohlcv`: args `symbol` (required), `interval` (default `1D`), `count` (default 300, max 5000), `summary`; no date range. Atlas sends `start_date`/`end_date`.
- The proxy names a tool `mcp-tv-` plus its name with hyphens (`get_documents` → `mcp-tv-get-documents`), so `mcp-tv-get-earnings-calendar` and `mcp-tv-get-ohlcv` stay.

## What to build

- `atlas.tradingview.client.calendar`: send `{"symbols": [symbol, ...], "date_from": "YYYY-MM-DD", "date_to": "YYYY-MM-DD"}`; one call may carry several of a theme's symbols (the job batches the companies, e.g. up to 20 a call). Parse defensively: keep only the dates, period and status; drop consensus or estimate fields on the way in, never store them.
- `daily_bars`: send `{"symbol", "interval": "1D", "count": N}` with N the trading days back to the requested start (capped at 5000); filter to the window in Atlas.
- A cap across processes: before each TradingView call, count the `tradingview_request` rows of the last 60 seconds (all processes, all jobs) and wait until fewer than `ATLAS_TRADINGVIEW_MAX_PER_MINUTE` (default 50, half TradingView's limit, leaving the rest to the owner); keep the per-process bucket as a second bound. Document it in the settings comment and `docs/decisions.md` (extend "The TradingView override, extended for the agents" with the limit and the cap).
- When an answer fails validation, store its first 4,000 characters in the job's artifacts (`unparsed_answer`) so the lead can fit the shape from one live call; the job fails cleanly, nothing is stored.
- Fixtures under `tests/fixtures/tradingview/` updated to the documented argument names (still synthetic answers).

## Acceptance criteria

- [ ] HTTP-seam tests against the TradingView fake: the calendar call carries `symbols[]`/`date_from`/`date_to` and batches; consensus fields in an answer are not stored; `get_ohlcv` carries `count` and the window is filtered; the global cap waits when the last minute holds the cap's worth of recorded calls (two clients sharing one database); a malformed answer lands in `unparsed_answer`.
- [ ] One live calendar job and one price read on production after deploy, the shapes confirmed or fitted (the lead).
