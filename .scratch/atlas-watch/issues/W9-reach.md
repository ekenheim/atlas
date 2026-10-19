# W9: the Watch's reach

**Status:** done
**Labels:** ready-for-agent
**Opened:** 2026-10-19 by the lead, after the two bake-offs (robotics, power equipment)

## Why

Two bake-offs on 2026-10-19 (`docs/experiments.md` on branch `bakeoff/robotics`, `.scratch/bakeoff/`) set Atlas's architect Watch run against an open Claude Code session with web tools. The open session cited 11 primary documents per theme; Atlas cited 0 on any step. Its rules held; its reach failed, for two reasons seen in the tool traces:

1. `update_chokepoint` refused step sets citing leads the session itself had just found (`web_search`, `filing_search`) as `created_after_as_of`: a Watch session's as-of time is its own start, so every lead it finds is "after" it (5 refusals in the power run, 3 in robotics). Issues already had the right rule (allowed when the same session opened them).
2. `fetch_page` needed the slug of a company Atlas has, so nothing could be archived in a greenfield theme (`unknown_company` for MP Materials, GE Vernova, Howmet), and a government notice has no company at all.

## What

- **A. In-session leads count.** A lead the citing session's own search found (or saw again) is not refused `created_after_as_of`; one first seen after the as-of time by anything else still is. A lead that dates itself after the as-of time is refused whoever found it.
- **B. `fetch_page` beyond the universe.** By name with an optional CIK or LEI: resolved through the counterparty machinery (a `counterparty` company), then fetched. A publisher-only fetch for a page whose publisher is not a company (a government or regulator notice): a `publisher` company row named from the site register. Counterparties and publishers are never ingested, never seeds, never a theme's companies.
- **C. SEC filings by URL.** An EDGAR Archives URL fetched for the company with that CIK is Tier A (`public_issuer`), available from the filing's acceptance (the submissions index), through the fetch gate (sec.gov in the register, SEC's fair-access terms) with the SEC User-Agent.

## Acceptance

- [x] A Watch session's step set citing a lead its own search found is accepted; one citing a lead another session found after the as-of time is still refused (and one dated after the as-of time too).
- [x] `fetch_page` by name + CIK of a non-universe company creates a counterparty and archives the page; `record_fact` in that session quotes it.
- [x] A publisher-only fetch archives a government page, and it can be quoted as a Fact.
- [x] An EDGAR Archives URL fetched for its filer is Tier A.
- [x] Isolated sessions are refused every new path.
- [x] ruff, pyright clean; the touched test modules pass.

Decision: `docs/decisions.md`, "The Watch's reach (Chokepoint Watch ticket W9)". Log: `docs/implementation-log.md`, 2026-10-19.
