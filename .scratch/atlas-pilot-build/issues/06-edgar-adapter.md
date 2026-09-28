# 06: SEC EDGAR adapter

**What to build:** Atlas can discover and fetch Lumentum's EDGAR submissions, filings and companyfacts politely and deterministically. It implements the common SourceAdapter protocol, with a fixture adapter replaying recorded EDGAR responses. Spec Part A: Source adapters, stories 15–22.

**Blocked by:** 01 (Walking skeleton)

**Status:** done

- [x] Every request carries the configured User-Agent; one process-wide limiter caps requests at 10/s
- [x] The mocked-429 test passes: Retry-After is honored, attempts are recorded, and the call eventually succeeds
- [x] Conditional requests (ETag / If-Modified-Since) are used where available
- [x] `acceptanceDateTime` is surfaced for each filing
- [x] A live SEC smoke test exists behind an opt-in marker and is excluded from CI
