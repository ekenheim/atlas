# 04: Exchange ingest path, HKEXnews blocked, manual import (Zhongji Innolight)

**What to build:** Innolight (HKEX 03308) is ingested from HKEXnews end to end: discovery, fetch, ledger, parse (PDF) and retention. `available_at` is the exchange's publication timestamp (basis `publisher_timestamp`). The robots/terms gate is recorded per fetch; a source forbidding automation produces a visible `blocked` fetch status instead of a fetch.

Spec: `.scratch/atlas-phase3-6a/spec.md`.

**Scope change (2026-09-29):** the HKEX Terms of Use prohibit automated access to hkexnews (a licensed IIS feed or written consent is required), so Atlas never fetches HKEXnews. This ticket builds the reusable exchange ingest path and records HKEXnews as `blocked`. It also adds an audited manual import, so the owner can add documents fetched by hand with their origin URL and publication time. The acceptance criteria below that assume automated HKEXnews fetching are superseded by this change.

**Blocked by:** 01 (Photonics universe); 03 (PDF parsing and language handling)

**Status:** ready-for-agent

- [ ] A `SourceAdapter` for HKEXnews, tested from recorded responses
- [ ] Ingest of the fixture records Source Versions with `publisher_timestamp` availability and enqueues retains for English documents
- [ ] Each fetch observation records the allowing gate; a disallowed path records `blocked` and is visible in the API
- [ ] Innolight's own IR site is never fetched (its robots.txt is `Disallow: /`)
- [ ] Docs: the source and its terms in `docs/decisions.md`
