# The prediction record

Type: task
Status: open
Blocked by: 01

## What to build

### Recording a prediction

The first time a prediction's ID is seen in a stored ledger (a theme's or the council's), it becomes one `ledger_prediction` row. The row holds the theme, the ID, the chokepoint, the date made, the deadline, the text, the source type, and the edition it came from.

Later editions never change the row. A change in a later edition is a finding for ticket 02.

### Its state

The state is derived, never stored:
- `open` before the deadline;
- `lapsed` after the deadline, with no settlement;
- `met` or `missed` once a later edition settles it.

A settlement is stored insert-only in `ledger_prediction_settlement`: the edition, the state, `settled_on`, the quote and the URL. Its quote goes through ticket 04's check like any other.

### The route

`GET /api/v1/predictions?state=&theme=&due_before=`.

This replaces nothing. The Hypothesis predictions keep their own route, under their own name, until ticket 07.

### Pricing the holders

Each holder name goes through `atlas.identity.service.resolve_mention`.

A holder that resolves to a listed company with a TradingView symbol may get a call: a `call_record` with origin `ledger` and the chokepoint's first edition date as `made_at`. Its checkpoints come from the existing `settle_calls`.

Holders that do not resolve are left unpriced, and that is not an error. This includes states and private companies; nuclear and quantum often name state bodies.

## Tests

- The fixtures give 27 theme predictions and 4 of the council's.
- A later edition that settles one gives `met` or `missed`.
- A prediction past its deadline with no settlement reads `lapsed`.
- A council prediction is recorded under `council`.

## Done when

- [ ] Production lists the 2026-10-19 predictions with their deadlines.
