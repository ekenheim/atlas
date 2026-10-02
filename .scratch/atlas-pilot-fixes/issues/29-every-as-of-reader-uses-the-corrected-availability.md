# 29: Every as-of reader uses the corrected availability

**What to build:** No Source Version enters an as-of reading before it was public. The corrected availability (`source_version_availability`, migration 0012: EDGAR dissemination time for filings accepted after hours) is the one every as-of comparison uses.

Evidence: an external review by Codex (the owner shared it on 2026-10-02); the lead verified the finding in the code before writing this ticket. The view exists and ten modules read it, but the investigation's document choice compares the raw column: `backend/atlas/investigations/tasks.py`, the pointed documents (`v.available_at <= :as_of` near the reading-pointer query), the latest documents and the document floor of pilot fix 24 all use `source_version.available_at`; so does the scenario Assertion check (`backend/atlas/scenarios/sources.py`). An after-hours filing could therefore be read up to a day before it was public. About 50 queries in `backend/atlas` read `source_version` directly; most do not compare with an as-of time, and some do.

- Every comparison of a Source Version's availability with an as-of time, a cutoff or a "since" reads the view (or a helper over it); a reader that only displays `available_at` may keep the column, and says which it shows.
- A test that fails on a new raw comparison: a unit test over `backend/atlas` that finds `available_at` compared with `as_of`, `cutoff` or a bound parameter in SQL text outside the view's own module, with an allow-list for the readers that are right as they are.
- An integration test at the investigation seam: a filing whose recorded `available_at` is before `as_of` and whose corrected availability is after it is not read.
- `docs/decisions.md`: the rule restated where the investigation reads, scenarios and replay are described.

**Blocked by:** None

**Status:** ready-for-agent (ships with the memory-quality release: it is the temporal-integrity rule, which the trust gate rests on)

- [ ] The investigation seam test above; the same for a scenario's Assertion source.
- [ ] The lint-style unit test, with its allow-list and a reason for each entry.
- [ ] Decision entry; `AGENTS.md` line if a command or setting changes.
