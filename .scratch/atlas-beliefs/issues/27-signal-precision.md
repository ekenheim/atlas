# 27: Archive signals: negation, pricing on input costs, one document's share of the top

Type: build
Status: in-review
Blocked by: none

## Why

Ticket 18's measures (2026-10-15, `scripts/signal_replay.py`, reports in `.scratch/live-runs/signal-replay-axt/` and `signal-precision-q/`):
- **The AXT replay** as of 2025-08-31 (750 documents, 293 hits): AXT's 31 July 2025 sentence ranks **1st**; "new orders on pretty much a daily basis" 7th; the 1 May "the other players both cannot keep up" 10th. Met.
- **Precision**, the top 20 of the last quarter (2026-07-15 to 2026-10-15), judged by the lead: **11 of 20** real cues (bar 12). The misses: a negation scored as the cue ("they are not sold out"; in the AXT replay also Fabrinet's "we have no capacity constraints", ranks 3 and 4); pricing_power on cost pass-through ("a price increase in the input cost", price clauses in contracts, a margin line); generic lines ("record backlog", "investing in capacity to address demand"). One document filled 8 of the 20 (AXT's Q2 2026 call), crowding other companies out.

## What to build

- **Negation scope** in `atlas.discovery.signals`: a cue phrase preceded in its clause by a negator (no, not, never, without, n't, none) that governs it ("not sold out", "no capacity constraints", "not constrained") is not a match; a negation that is part of the cue ("cannot keep up", "not taking orders", "can't get enough") stays a match (the phrase itself contains it). Unit tests both ways.
- **pricing_power** means a price rise the company can impose because of scarcity or demand ("raising prices", "price increases stick", "pricing power", "customers accept higher prices"), not a cost pass-through ("input cost", "raw material costs", "pass through", "inflation", "surcharge") or a contract mechanic; down-weight or drop those, with tests.
- **Generic backlog and capacity** lines ("record backlog" alone, "investing in capacity to meet demand") score below the threshold unless a figure or a second family supports them.
- **One document's share of the ranking:** the ranked read (`GET /leads?origin=archive_signal`, `signal_leads`, the replay script) shows at most 3 hits per document in its top results (the rest after), stored leads unchanged. Configurable in `signals.yaml`.
- The config version bumps; re-scoring of stored leads is not needed (the scan stores the scorer version; new scans use the new one).

## Acceptance criteria

- [x] Unit tests for each rule (negation both ways, pass-through, generic lines, the per-document cap) with literal scores; existing tests still pass or are updated with a stated reason.
- [ ] The two replays again (the lead): AXT's 31 July sentence in the top five as of 2025-08-31; precision of the last quarter's top 20 at least 12 of 20. Both in `docs/experiments.md`.
