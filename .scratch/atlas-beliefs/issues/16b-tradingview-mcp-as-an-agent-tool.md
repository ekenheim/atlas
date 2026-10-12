# 16b: The TradingView MCP proxy as an agent tool, under the owner's override

Type: grilling
Status: open
Blocked by: 15

## Question

The owner's proxy exposes 26 tools; Atlas calls three. Which may the agents call, under what rules, recorded in `docs/decisions.md` ("Owner override: TradingView as a source", extended) by the owner: transcripts and documents only through Atlas's ingest (Facts at spans, never from an MCP answer); news and the earnings calendar as leads; consensus and prices as `estimated` scenario inputs and the "what the market expects" paragraph, never Evidence; price history (`mcp-tv-get-ohlcv`) for settling predictions (ticket 19) and the early-signal replays, never for a Belief; every use recording the override. Then the agent prompts name the tools each may call. Resolved when the decision is recorded and one Scout run with TradingView leads and one Hypothesis with the market-expectations paragraph exist.
