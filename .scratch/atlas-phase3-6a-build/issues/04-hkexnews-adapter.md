# 04: HKEXnews adapter (Zhongji Innolight)

**What to build:** Innolight (HKEX 03308) is ingested from HKEXnews end to end: discovery, fetch, ledger, parse (PDF) and retention. `available_at` is the exchange's publication timestamp (basis `publisher_timestamp`). The robots/terms gate is recorded per fetch; a source forbidding automation produces a visible `blocked` fetch status instead of a fetch.

Spec: `.scratch/atlas-phase3-6a/spec.md`.

**Blocked by:** 01 (Photonics universe); 03 (PDF parsing and language handling)

**Status:** ready-for-agent

- [ ] A `SourceAdapter` for HKEXnews, tested from recorded responses
- [ ] Ingest of the fixture records Source Versions with `publisher_timestamp` availability and enqueues retains for English documents
- [ ] Each fetch observation records the allowing gate; a disallowed path records `blocked` and is visible in the API
- [ ] Innolight's own IR site is never fetched (its robots.txt is `Disallow: /`)
- [ ] Docs: the source and its terms in `docs/decisions.md`
