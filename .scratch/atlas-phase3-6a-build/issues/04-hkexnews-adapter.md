# 04: HKEXnews adapter (Zhongji Innolight)

**What to build:** Innolight (HKEX 03308) comes in from HKEXnews without Atlas fetching HKEXnews. The HKEX Terms of Use (updated 19 Aug 2025, covering hkexnews.hk) forbid robots, scraping and text/data mining; the automated route is the licensed Issuer Information feed Service (IIS) or HKEX's written consent, neither of which is held (scope change from the lead, 2026-09-29). So:

- a reusable exchange ingest path: the `ingest` job dispatches on the company's `source_path`; every request passes a per-fetch terms/robots gate; a blocked request is a visible `blocked` fetch gate decision instead of a fetch (tickets 05/06 reuse it for the FCA NSM and the AMF info-financière API);
- HKEXnews is registered with the terms block "blocked: HKEX Terms of Use prohibit automated access (IIS licence or written consent required)", so an `exchange:hkex` ingest records that and fetches nothing;
- a manual import path (`atlas sources import`) for documents the owner fetched by hand: `available_at` is the given publication time (basis `publisher_timestamp`); parsed, Evidence Family, retained if English, audited, idempotent.

Spec: `.scratch/atlas-phase3-6a/spec.md`.

**Blocked by:** 01 (Photonics universe); 03 (PDF parsing and language handling)

**Status:** done

- [x] The ingest job dispatches on `source_path`; exchange requests pass the terms/robots gate, each fetch observation records the allowing gate, and a disallowed request records `blocked`, visible in the API
- [x] An `exchange:hkex` ingest records a `blocked` decision with the HKEX terms reason and fetches nothing (tested)
- [x] `atlas sources import` records a hand-fetched document (provider `manual_import`, origin URL, owner as actor, `publisher_timestamp` availability), parses it, assigns its Evidence Family, retains it if English; audited; re-importing the same bytes is idempotent (tested at the CLI seam)
- [x] robots.txt parsing and honouring is real (RFC 9309) and tested with fixture robots files
- [x] Innolight's own IR site is never fetched (its robots.txt is `Disallow: /`)
- [x] Docs: the decision and the quoted terms in `docs/decisions.md`

The HKEXnews adapter itself is built and tested from hand-written fixtures (not recorded; HKEXnews can't be fetched) for the day a licence or consent is recorded.
