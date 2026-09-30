---
name: pilot-review
description: Run a research pilot investigation on production and review its output against the cited spans. Use when running or re-running a pilot investigation, reviewing an investigation's research card, Claims or edges for usefulness, or writing up a pilot result in `.scratch/pilot/results.md`.
---

# Pilot review

The pilot measures **research usefulness**, not traceability: would a researcher have been saved work by this card, and can every finding be trusted from its span? Each review ends in a section of `.scratch/pilot/results.md` and, for each defect found, a ticket in `.scratch/atlas-pilot-fixes/issues/` (see `docs/agents/issue-tracker.md`). The questions and seeds are in `.scratch/pilot/pilot-plan.md`.

## 1. Run

Production API: `https://atlas.ekenhome.se/api/v1` (read-only checks: `/metrics` for `atlas_build_info`, `/health/ready`, `/queue` for budgets and pauses).

1. Confirm the version under test and that the budgets have room (`/queue`).
2. `POST /investigations` with the plan's question verbatim and `seed_company_ids` from `/companies` by `display_name`. Record the ID and the version.
3. Poll `GET /investigations/{id}` until `status` is not `running` (a `paused` investigation waits for an LLM budget; say so rather than treating it as a stop).
4. Save the full JSON to the scratchpad; the review works from it and from `GET /runs/{run_id}/role-calls`, `GET /discoveries/{id}`, `GET /claim-extractions/{id}` and `GET /relationships?sort=created_at&order=desc`.

## 2. Review every accepted Claim

Completion criterion: **every accepted Claim in `evidence` has a verdict, and every task's artifacts are explained.** Read each quote whole (`quote` in `evidence`, never the card's paraphrase), then judge:

- **The verb belongs to the object.** The predicate's cue must act on the object text in the same clause. A verb in a neighbouring clause ("we expand X, while also operating Y" → `expands_capacity_for` Y) is wrong even when the edge is `machine_reviewed`. Review machine-reviewed edges with the same care as the exceptions queue.
- **The layer is in the quote.** A `layer` the text never names (generic "materials, components, suppliers" tagged `substrate`) is over-tagging; the Investigator tends to tag the question's layer, not the quote's.
- **Boilerplate is not evidence.** Risk-factor sentences that every filer writes (sole or limited sources for "certain components") state no bottleneck; count them as worthless even when true.
- **On the question.** A true fact about another segment or product line is off-topic; note it, don't count it as saved work.
- **Counterparties.** A company object outside the universe must be a real `counterparty` (`GET /companies?role=counterparty`) resolved from the registry; check the `named_as` matches the quote.

Then the tasks, from `tasks[*].artifacts` and the card's `searched` and `read`:

- **Scout:** are the queries layer-tagged and specific? Are the kept leads industry sources or the companies' own pages? (`leads` with `score` and `reasons`.)
- **Investigators:** documents taken vs. documents with passages (`read[*].documents[*].sections`); rejection reasons by code (`quote_mismatch` and `quote_outside_passage` point at parser artifacts or offsets, `party_not_in_quote` and `no_directional_language` at the prompt).
- **Skeptic:** `documents` and `passages` read, counterevidence accepted and independent; a Skeptic that only searched read nothing.
- **Financial Analyst:** `sourced` vs `missing` inputs; an all-`missing` table with "no XBRL figure" means the observations are absent, which is an ingest problem, not a prompt problem (`GET /companies/{id}/financials?as_of=`).
- **Editor:** verdict, findings against their `claim_ids`, and whether the open questions name what the next round should read.

## 3. Write it up

Append to `.scratch/pilot/results.md` under the investigation's heading, in this order and with these labels, so runs compare: **ID / seeds / stop / usage** (tokens in and out, role calls, wall time); **Saved work** (correct, useful, cited findings, quoting the span); **Unsupported or wrong** (each bad Claim, its review state, why); **Missed evidence** (what the read documents contain that wasn't surfaced; what wasn't read and why); **Corrections needed** (the owner's review decisions, listed edge by edge; the owner makes them, not the agent); **Cost and latency**; **New defects** (one line each, pointing at its ticket); **Assessment** (precision as accepted-and-right over accepted; coverage as what was read over what was taken).

Then: one ticket per defect with the production IDs (investigation, discovery, extraction, role call) as evidence, `**Status:** ready-for-agent` when the fix is clear and `needs-triage` when it needs a decision; a one-paragraph `docs/implementation-log.md` entry pointing at the results section; commit and push `main`.

## Owner decisions

Approving or rejecting an edge (`POST /relationships/{id}/review`) is the owner's act, and so is deleting nothing: list the decisions with your recommendation and the reason; never apply them.
