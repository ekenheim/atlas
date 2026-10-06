# The memory probe reports balance across companies and time

Type: build
Status: done
Blocked by: none

## Why

The imbalance of tickets 22 and 23 was found by hand on 2026-10-06 (a ledger download, per-version memory reads, the probe's ranking joined to document dates). The probe should show it every time it runs, so a skew is a number in the report, not something the owner notices.

The probe set itself stays as it is: its five probes are the pilot's five questions (`coherent-demand` is investigation 5's question, so its Coherent lean is the question's, not the bank's), and a fixed set is what makes before and after comparable.

## What to build

In `scripts/memory_probe.py`'s report (`results.json` and `summary.md`), from data the recalls already return plus one `GET /api/v1/source-versions/{id}` per distinct pointed version (cached in the run):

- **By company:** for every researched company in the universe (`GET /api/v1/companies?role=researched`), its pointers, pointer weight and share of the total weight, **including companies with none** (listed as 0, so an absent company shows).
- **By document age:** the share of pointers whose Source Version's `available_at` is before the intake window (`--window-days`, default 730), overall and per company.
- A line at the top of `summary.md` naming companies at 0 weight and any company whose pre-window share is above 25%.

Unit-test the pure part (the measures from a recorded answer set) in `tests/unit/`; the script stays network-only at run time.

## Done when

- [x] The report has both tables and the top line; a unit test covers the measures.
- [ ] Run once on production before tickets 22/23's ops and once after, both recorded in ticket 22.
