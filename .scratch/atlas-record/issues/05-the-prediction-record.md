# The prediction record

Type: task
Status: ready-for-human
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

`GET /api/v1/ledger-predictions?state=&theme=&due_before=` (built under this name: `/api/v1/predictions` is the Hypothesis predictions' and stays so until ticket 07), and `GET /api/v1/ledger-predictions/{id}`.

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


## Comments

### 2026-10-20: built, without the holders' calls (implementer)

Built: migration `0124` (`ledger_prediction`, `ledger_prediction_settlement`, insert-only by trigger), `atlas.record.predictions` (`record_predictions`, called in `Editions.import_page`'s transaction; the derived state; the reads), `GET /api/v1/ledger-predictions?state=&theme=&due_before=` and `GET /api/v1/ledger-predictions/{id}`.

Decisions to confirm:
- **Route name.** `/api/v1/predictions` is the Hypothesis predictions' (`atlas.api.calls`), so this is `/ledger-predictions`. Ticket 07 can rename it when the Hypothesis ones go.
- **Deadline.** The ledger writes it as text. `deadline` and `made` are kept as written; `deadline_on` is the day it reads as (`2027-02-28`; a month such as `2027-03` is its last day), else null. A null `deadline_on` never lapses and is never `due_before`. A prediction lapses the day after its deadline day (as a Hypothesis's does).
- **`due_before`** is inclusive: deadline day on or before the given day.
- **Settlement.** Only `state` `met` or `missed` with a non-blank `settled_on` counts. The first edition carrying one wins; a later different settlement (`met` then `missed`, or un-settled) is skipped here and is ticket 02's `prediction_unsettled` / rewrite finding. A prediction first named in the same edition that settles it is recorded and settled together.
- **Audit.** One `ledger_prediction.recorded` event per prediction and one `ledger_prediction.settled` per settlement (the entity is the `ledger_prediction` row).
- **Ticket 01's truncate test** now says `TRUNCATE ledger_edition CASCADE`: with a foreign key to the table, plain `TRUNCATE` is refused by Postgres before the trigger runs (still refused, by a different error). Ticket 02 will need the same for its own tables.
- **Not done here:** the settlement's quote is not checked (ticket 04). An edition imported before this migration is not back-filled: the same bytes again say `unchanged` and record nothing. Production holds no editions yet, so the lead imports the eight pages after the release and they record their predictions then.

### Follow-up: pricing the holders (calls with origin `ledger`), not built, for the lead

What I found reading `atlas.calls` and `atlas.identity.service`:
1. **`call_record`'s origin.** Migration `0113` has `CHECK (origin IN ('belief', 'hypothesis', 'signal'))`, `origin_id uuid NOT NULL`, `UNIQUE (origin, origin_id)` and `CHECK ((origin = 'signal') = (lead_id IS NOT NULL))`; `atlas.calls.model.Origin` is the same literal and the calls API schema carries it (the client regenerates). `ledger` needs a migration that widens the CHECK, the literal, and a decision on `origin_id`: the ticket dates a call by the chokepoint's first edition, but a chokepoint has no table (the edition ledger holds it in JSONB), so `origin_id` would be a uuid5 of `theme:chokepoint_id`, or a `ledger_chokepoint` row from ticket 06. `made_at` should be the first edition's `read_at` (when Atlas could first have known it), not its `as_of` day: every other origin is dated by a database event, never a request or an as-of time.
2. **`call_company` needs a `company` row** (`company_id NOT NULL REFERENCES company`) and `record_call` takes the TradingView symbol only from the theme config (`company_symbols`: `universe.companies[slug].tradingview_symbol`). A holder that `resolve_mention` matches in the universe (`find_in_universe`, no network) is priced if the config gives it a symbol. A holder it does not match locally goes to `EntityResolver` (SEC, GLEIF, OpenFIGI: live calls, `ATLAS_SEC_USER_AGENT`), so it must run in a job, not the import transaction, and an external match has no `company_id` unless a counterparty is created (`atlas.counterparties`, which has no symbol). So most holders (Micron, GE Vernova, Howmet) would stay unpriced unless the symbol comes from somewhere: the resolution's listing (`security`, composite FIGI, ticker and MIC) mapped to a TradingView `EXCHANGE:TICKER`, which Atlas does not do today, or the config.
3. **The benchmark.** `settle_calls` benchmarks against the theme's researched companies with a symbol (`_benchmarks`, `universe.themes.get(theme)`). The ledger themes `nuclear` and `quantum` (and the council) are not config themes, and robotics, power-equipment and aerospace-defence have no companies yet, so a `ledger` call there has an empty benchmark (`benchmark_members` 0, `relative_change` null) until the benchmark is a ledger theme's resolved holders.
4. **Holder strings** are names, sometimes with notes and states (`holders: list[str]`); the resolver takes a `Mention(name, ...)`. Unresolved ones are left unpriced with `call_unpriced` (`no_symbol`), which already exists and is not an error.

A small version that fits: widen the origin; run a job after an edition import that resolves each holder with `find_in_universe` only (no network), makes one call per chokepoint when at least one holder is a researched company with a symbol, and leaves the rest unpriced; defer the external resolver and the TradingView mapping.
