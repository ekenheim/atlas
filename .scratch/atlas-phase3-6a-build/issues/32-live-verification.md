# 32: Live verification of every Phase 3–6a part

**What to build and run:** An opt-in live verification suite that proves each part works against the real services, not only against fixtures. It is small and bounded, and every run writes a report. Owner direction (2026-09-30): "I am more concerned that we get all the functionality working and verifying these parts of the project."

Each check runs against a throwaway local Postgres and archive. Hindsight is either a throwaway bank on the cluster Hindsight (as the Phase 2 live suite does) or the local Compose Hindsight, and it is always deleted afterwards. Every check records calls, tokens and pass/fail:

1. **SEC live:** ingest one company with `--limit`, parse, run triage (live MiniMax), retain the selected sections, then recall one question with resolved citations.
2. **Exchanges live:** FCA NSM (IQE) and AMF (Soitec) discovery plus one document each, through the fetch gate, with decisions recorded.
3. **TradingView live** (owner override): catalog and one transcript for one symbol, stored as Tier B with the override mark. The token comes from `atlas tradingview login`.
4. **Discovery:** the Scout on MiniMax plus SearXNG produces leads, then Candidates from the mention extractor (entity resolution live against SEC, GLEIF and OpenFIGI).
5. **Claims → Relationships:** extraction on a recorded supplier-rich filing, then the Reviewer on MiniMax, giving a `machine_reviewed` or exception edge.
6. **Investigation end to end:** Scout → Investigator → Skeptic ∥ Financial Analyst → Editor, ending in a stop reason. Then a Hypothesis draft, a scenario (byte-identical recompute), and publish with a snapshot once ticket 20 exists.
7. **Identity:** `atlas companies resolve` for two companies, with pending reviews listed.

**Blocked by:** the wave-4 merge (06, 15, 19, 23, 30, the triage fix, 31). Parts 6 and 7 extend as 20–22 land.

**Status:** done (the harness; the live run and its LIVE log entry are the lead's, the last two boxes)

- [x] `scripts/live-verify.sh [--only <part>] [--rehearse]` with the same two locks as the live suite (`live` marker plus `ATLAS_LIVE_TESTS=1`). It never runs in CI. It refuses to start without `.env` LiteLLM settings, and it prints no secrets.
- [x] Hard caps: at most ~40 MiniMax calls and ~25 Hindsight retain operations per full run. Each part has its own budget, reported.
- [x] `--rehearse` runs every part against the fakes, so the harness itself is CI-verifiable.
- [ ] Report (JSON plus a Markdown table) under the gitignored `.scratch/live-runs/`. Results go into `docs/implementation-log.md` as LIVE, with exactly what ran.
- [ ] The lead runs it with the owner's go-ahead (given 2026-09-30) and fixes what fails.
