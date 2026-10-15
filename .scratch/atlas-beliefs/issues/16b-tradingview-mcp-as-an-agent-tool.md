# 16b: The TradingView MCP proxy as an agent tool, under the owner's override

Type: build
Status: in-review
Blocked by: 15

## Question

The owner's proxy exposes 26 tools; Atlas calls three. Which may the agents call, under what rules, recorded in `docs/decisions.md` ("Owner override: TradingView as a source", extended) by the owner: transcripts and documents only through Atlas's ingest (Facts at spans, never from an MCP answer); news and the earnings calendar as leads; consensus and prices as `estimated` scenario inputs and the "what the market expects" paragraph, never Evidence; price history (`mcp-tv-get-ohlcv`) for settling predictions (ticket 19) and the early-signal replays, never for a Belief; every use recording the override. Then the agent prompts name the tools each may call. Resolved when the decision is recorded and one Scout run with TradingView leads and one Hypothesis with the market-expectations paragraph exist.

## Answer (the owner, 2026-10-15)

Recorded in `docs/decisions.md`, "The TradingView override, extended for the agents": the earnings calendar as leads and price history only for settlement and replays, both through Atlas only; no consensus or current prices, no other proxy tool. The market-expectations paragraph is dropped from this ticket.

## What to build

- `atlas.tradingview.client`: the proxy's earnings-calendar tool (its name from the proxy's `tools/list`; synthetic fixture) and `mcp-tv-get-ohlcv`, bounded and recorded like the three tools today, each stored item marked with the override.
- The calendar: a `tradingview_calendar` job (or a step of `tradingview_catalog`) storing upcoming and recent reporting dates per universe company as leads (`origin: tradingview_calendar`), read by `GET /api/v1/leads` and by an Atlas MCP tool `upcoming_reports` (theme, window) the Scout calls.
- Price history: a read-only service and route returning daily closes for a company over a window, for ticket 19's settlement and the replays; not exposed as an MCP tool to the research agents.

## Acceptance criteria

- [x] HTTP-seam tests against the TradingView fake: the calendar leads stored and listed, the override marked, the budget counted; the OHLCV read; off by default.
- [ ] One Scout run (ticket 16) uses `upcoming_reports`.
