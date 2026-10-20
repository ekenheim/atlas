# The rewrite check

Type: task
Status: ready-for-human
Blocked by: 01

## What to build

When an edition is stored, compare its ledger with the same theme's previous edition. "Previous" means the one before it by `as_of`, then by edition number.

Record each difference insert-only in `ledger_rewrite`, with the edition, the previous edition, the kind, the ID, and the values before and after. The kinds are:
- `prediction_changed`: the `text`, `deadline`, `chokepoint` or `made` of a past prediction differs.
- `prediction_removed`: a prediction's ID is gone.
- `prediction_unsettled`: a prediction settled before is open again, or its settlement changed.
- `chokepoint_vanished`: a chokepoint's ID is gone, and it was not marked `killed` in this edition or an earlier one.
- `id_reused`: an ID's name or layer changed beyond wording. Two names that are equal after normalising case, punctuation and whitespace are the same; anything else is reported for the reviewer to read.
- `date_moved_later`: `first_seen` or `earliest_evidence` moved later.
- `edition_not_increasing`: the edition number did not rise.

A missing optional field is not a finding.

The council's ledger is compared with its previous edition the same way: its board items by ID, its predictions, and the `first_seen` of its contradictions.

Expose:
- `GET /api/v1/editions/{id}/rewrites`;
- `GET /api/v1/rewrites?theme=&since=`;
- the metric `atlas_ledger_rewrites_total{kind}`.

## Tests

- Pairs of hand-edited copies of the fixtures, one pair per kind: each kind is found once.
- An unchanged second edition finds nothing.
- A ledger that lacks `earliest_evidence` finds nothing.

## Done when

- [x] A test finds each kind.
- [ ] The 2026-10-26 editions are checked on production.
