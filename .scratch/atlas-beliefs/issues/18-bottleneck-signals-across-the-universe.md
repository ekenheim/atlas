# 18: Bottleneck signals across the universe

Type: build
Status: in-review
Blocked by: none

## What to build

`atlas.discovery` over the archive: a nightly scan (`scan_signals` job, no LLM) of newly ingested sections for the Serenity cues (`configs/discovery/signals.yaml`: the early-signal case studies' phrases and the Reader's constraint vocabulary, weighted), each hit a `lead` of origin `archive_signal` with its quote, span, company and score; `GET /api/v1/leads?origin=archive_signal` ranked; the Scout prompt reads the ranked leads first. EDGAR full-text search and SearXNG stay the web channels.

## Acceptance criteria

- [ ] Worker tests on the fixtures; the AXT replay: the scan over documents available by 2025-08-31 ranks the 31 July 2025 sentence in its top five (recorded in `docs/experiments.md`).

## The lead's notes (2026-10-15)

The target, from `docs/research/early-signal-case-studies.md`: AXT's Q2 2025 call (2025-07-31), in Q&A, "the market is just growing too fast to be adequately serviced by just two players" (and, the same call, "new orders on pretty much a daily basis", "a backlog of more than $10 million"). Atlas's `directional_cue` finds no cue in the first two; that is the gap this ticket closes. **Not fitted to AXT:** AXT is a known winner (the bias the owner named: studying only winners), so the vocabulary stays general and the second measure below is precision across the whole universe.

## What to build (binding)

- `configs/discovery/signals.yaml` (versioned, validated at load like the lead-ranking config): cue families, each with phrases or patterns and a weight: few suppliers ("two players", "only supplier", "duopoly", "sole source", "handful of suppliers"); demand beyond supply ("growing too fast", "cannot keep up", "can't get enough", "demand exceeds/outstrips supply", "undersupply", "sold out", "on allocation", "not taking orders", "orders daily"); lead times and backlog ("lead times extended", "record backlog", "backlog of"); capacity ("doubling capacity", "capacity constrained", "fully utilized", "adding capacity"); gates ("export permit", "licence", "qualification takes"); pricing power ("raising prices", "price increases stick"). Generic risk-factor wording is down-weighted (the section is Item 1A, or the sentence says "could"/"may" with "shortages").
- `atlas.discovery.signals`: a pure scorer over a section's parsed text, sentence by sentence: the families matched, weighted, a bonus when two families co-occur within one paragraph, a bonus for a figure (a backlog amount, a percentage of supply), a transcript speaker who is the company's own management (`atlas.claims.speakers`; an analyst's question scores lower), a penalty for boilerplate; returns ranked hits with the sentence's span.
- A `scan_signals` job (no LLM, not pausable, backfill class): the sections of Source Versions ingested since the last scan (or a given version list / `--since`), each hit stored as a `lead` of origin `archive_signal` (migration `0111`, down_revision `0110`: the origin; the hit's quote, span, source version, company, families and score, insert-only), deduplicated by span; `GET /api/v1/leads?origin=archive_signal&known_by=&company_id=` ranked by score, never Evidence. `atlas worker` enqueues it daily after ingest (`ATLAS_SIGNAL_SCAN_AT`, default 03:00 UTC; empty: never).
- An Atlas MCP tool `signal_leads` (theme, since, limit): the theme's archive-signal leads available by the session's as-of, ranked, each with its quote and the source version and span so the agent reads the window and records a Fact itself (a lead is never a Fact). `scout.md` and the Scout routine wrapper (`agent/prompts/scout.md`, its Tools line and the prompt-tools test) read the ranked leads first.
- `scripts/signal_replay.py --as-of 2025-08-31T00:00:00Z [--companies slug,...] [--top N] [--base-url]`: read-only against a running Atlas (like `scripts/pilot_baseline.py`: the companies' parsed Source Versions available by the as-of through the API), runs the same scorer, prints the top hits with rank, company, title, date and a 200-character sentence, writes `.scratch/live-runs/<stamp>-signal-replay/`.

## Acceptance criteria (replacing the above)

- [x] Worker and HTTP-seam tests on fixtures: hits stored once per span, ranked, the as-of bound in `GET /leads` and `signal_leads`, boilerplate down-weighted, an analyst's question below management's answer; the config validated; the prompt-tools test updated.
- [ ] The AXT replay (the lead): `signal_replay.py --as-of 2025-08-31` over the 12 companies ranks the 31 July 2025 sentence (or a sentence of that call stating the same) in its top five; recorded in `docs/experiments.md`.
- [ ] Precision (the lead): the top 20 hits of a scan over the last quarter of the archive judged real bottleneck cues or not; at least 12 of 20.
