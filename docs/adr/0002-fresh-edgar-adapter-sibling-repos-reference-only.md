# A fresh EDGAR adapter; sibling repositories are reference only

Atlas writes its SEC EDGAR adapter from scratch against the `SourceAdapter` protocol (build plan §4.2; spec Part A "Source adapters"; ticket 06). It takes no code, data, services, databases, buckets or APIs from the owner's sibling repositories: `trading-research`, `alphaos` and `TradingDashboard`. Atlas may read them and cite them as reference. The charting session settled this for `trading-research` (`.scratch/atlas-pilot/map.md`, "The EDGAR adapter is written fresh"), and spec story 51 asks for it to be recorded. The build plan's Phase 0 task "inspect existing code and services, and document the reuse strategy" is answered here.

What the repositories are, from a read-only look on 2026-09-28:

- **`trading-research`** is the owner's manual trading-research operation: backtests, doctrine and pre-registrations. Its EDGAR code consists of scratch helpers (`scratch/plab/_ca_edgar.py`, `scripts/build_sec_fundamentals.py`). They use synchronous `requests`, per-script sleep throttles (roughly 3 to 8 requests per second), and fixed-sleep retries that ignore Retry-After. They make no conditional requests, keep no archive, hashes or ledger, key filings by filing date (`filingDate`, `filed`) rather than `acceptanceDateTime`, and hard-code the User-Agent contact in the source files.
- **`alphaos`** is at "Milestone 0": audit and planning documents for a systematic trading platform, with no platform code yet.
- **`TradingDashboard`** is a FastAPI and Postgres portfolio tracker, with a separate market-data pipeline (a personal paid price subscription into a MinIO bucket, with Yahoo as a fallback).

Why the adapter is fresh rather than adapted:

- Atlas's EDGAR contract shares almost nothing with those helpers. It is async with an injectable transport and one process-wide token bucket; it honors Retry-After and makes conditional requests; it surfaces `acceptanceDateTime`; it archives by content hash through the source ledger; and a fixture adapter replays recorded responses. Adapting the helpers would mean rewriting them anyway.
- The SEC User-Agent contact comes from env and is never committed. Code with the contact embedded can't be copied as-is.
- The sibling repositories are trading-oriented: sizing, execution and portfolio tracking are non-goals for Atlas (build plan §1.4). Sharing code or services would pull their assumptions and data into Atlas's evidence chain. Their market data is not an Atlas entitlement ([`source-licenses.md`](../source-licenses.md) §3.3).

## Consequences

- Ticket 06 builds the EDGAR adapter and its fixtures from scratch. No dependency on or import from a sibling repository, a vendored copy, or a runtime call to their services or buckets is allowed.
- Approaches can be reused with a citation: SEC pacing lessons, point-in-time discipline, the provider-register style of documenting data entitlements, and the restatement rule in `build_sec_fundamentals.py` as a cross-check for Phase 5. Atlas's own tests and fixtures still decide behavior.
- Reuse *inside* Atlas is unaffected: the Hindsight spike (`spikes/hindsight/`) and its recordings are Atlas's own contract-test source. So are the cluster services the spec reuses on purpose (Crunchy Postgres, MinIO, LiteLLM, SearXNG, Prometheus).
- Reversing this for a specific component takes a new ADR that supersedes this one for that component.
