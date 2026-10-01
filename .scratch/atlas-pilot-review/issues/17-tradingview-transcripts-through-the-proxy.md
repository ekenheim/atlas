# TradingView transcripts for the universe through the cluster proxy

Type: task
Status: claimed
Blocked by: none

## Question

The owner put TradingView's MCP server in the cluster behind a read-only proxy and asked the lead to use it (2026-10-01). Atlas 0.2.5's TradingView source works against it with configuration alone (`docs/decisions.md`, "TradingView through the cluster's MCP proxy"). Get the universe's earnings-call and conference transcripts into the archive and into Memory before the reviewed pilot runs:

- home-ops PR #7178 (the three settings; the nightly `tradingview_catalog` job per universe company) is merged by the owner;
- the first catalog jobs succeed in the cluster (the pods reach the proxy; no authorization error);
- for each seed company of the five investigations: transcripts in the ledger (provider `tradingview`, Tier B), parsed, and retained;
- what it costs: tool calls against the `tradingview` budget and Codex operations for the retains.

This also does the live check that build tickets 26 and 31 were paused for. The answer records the counts per company and anything the first jobs show (transcript parsing, speaker turns, the party check on spoken "we").

Open decision to record when the first transcript Claims exist: a management statement in a transcript is Tier B, and today only Tier A Evidence can make a `machine_reviewed` edge, so every transcript edge goes to the owner's queue.
