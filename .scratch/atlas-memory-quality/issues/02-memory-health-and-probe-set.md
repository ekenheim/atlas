# 02: Memory health and the probe set

**What to build:** The owner opens one read and sees what Memory holds and what it lost: per company and for the bank, the sections retained, failed (grouped by error), empty and pending, the observation scopes that exist, and whether each universe company is one entity or several. The lead runs one script and gets, for a fixed set of questions, what the reading index returns. Both are the before-and-after measure of the whole effort.

Spec: `.scratch/atlas-memory-quality/spec.md` ("Measuring"). Study: `docs/research/hindsight-memory-use.md`, findings 1 and 2.

- `GET /api/v1/memory/health[?company_id=]`: from Atlas's own records, sections by retain outcome and by company, failed sections grouped by a normalized error text (the count, the latest example, the first and last time), zero-fact and partial counts, pending by age; from Hindsight (read-only, no LLM call), the observation scopes with their counts and, for each universe company, the entities whose name matches it. A Hindsight read that fails makes its part of the answer `unavailable` with the reason; the rest still answers.
- `configs/memory/probes.yaml`: the five pilot questions (`.scratch/pilot/pilot-plan.md`, verbatim) and four Scout-style queries each (short, layer and product terms), each with its theme scope.
- `scripts/memory_probe.py [--base-url] [--out]`: runs each probe through `POST /api/v1/memory/recall` (no LLM call) and reports per probe and in total: memories returned, resolved citations, distinct sections, distinct companies, the share of observations, memories whose text another returned memory repeats, and the companies ranked by pointer weight. JSON and a Markdown summary under `.scratch/live-runs/<stamp>-memory-probe/`.
- The health read gets a row on an existing page of the frontend only if that is a few lines; otherwise the API alone.
- `docs/runbooks.md` gains "Memory health": what each number means and what to do about a failed group.

The lead, not the implementer, runs both against production after the deploy and writes the before-numbers into the implementation log.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] Integration test at the API seam: with sections in each retain outcome for two companies and two different error texts, the health read returns the counts per company and the error groups; with the Hindsight fake's scopes and entities, it returns them; with the fake failing, that part is `unavailable` and the status is still 200.
- [ ] Unit test of the probe report from a recorded recall answer: the counts, the duplicates and the ranking are the expected ones.
- [ ] The probes file is validated at load (a probe without a scope or with an unknown theme is refused).
- [ ] The API client is regenerated; `AGENTS.md` gains one line for the read and the script; the runbook entry exists.
