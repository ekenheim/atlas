# 16d: The earnings calendar in its confirmed shape

Type: build
Status: in-review
Blocked by: none

## Why

The first nightly `tradingview_calendar` job on production (2026-10-16 01:41 UTC, job `2f4380b8-35ba-5115-9c21-93aed58fce5e`, key `tradingview-calendar-2026-10-16`) failed `UnexpectedAnswer: mcp-tv-get-earnings-calendar: unexpected answer: 1 problems`, as ticket 16c foresaw: the answer's field names were Atlas's guess. The job's `unparsed_answer` (a skeleton: values replaced by their type except identifying keys and dates, consensus keys removed) shows the real shape:

```
{"success": <bool>,
 "data": {"count": <int>, "from": <str>, "to": <str>,
          "earnings": [{"symbol": "NASDAQ:LITE", "name": <str>, "description": <str>,
                        "close": <float>,
                        "fiscal_period_end": "2026-09-30",
                        "release_date": "2026-08-11",
                        "release_next_date": "2026-11-05",
                        "release_next_at": <str>,
                        "release_next_time_flag": 1,
                        "next_date_confirmed": <bool>,
                        "publication_type_next_fq": <int>,
                        ...consensus keys, removed by the skeleton}, ...]}}
```

Nine rows came back for the twelve symbols asked (LITE, COHR, AXTI, AAOI, FN, MRVL, MTSI, CIEN, STM; none for IQE, Soitec or Innolight). `fiscal_period_end` is the quarter the **next** release reports (MRVL and CIEN: 2026-10-31, their own fiscal quarters). One row per symbol holds two events: the most recent report and the next one. There is no event id and no fiscal year or period field.

## What to build

- `atlas.tradingview.client`: parse the confirmed shape (`data.earnings[]`, both keys required: another wrapper still fails the job with `unparsed_answer`, never an empty calendar) into `CalendarItem`s, up to two per row:
  - the **next** report: date `release_next_date`; status `confirmed` when `next_date_confirmed` is true, else `scheduled`; period = the quarter ending `fiscal_period_end`;
  - the **most recent** report: date `release_date`; status `reported`; period = the quarter ending three months before `fiscal_period_end` (the month end three months earlier), recorded as derived (e.g. `period_basis: "derived_from_next"` in the lead's calendar data). So when a scheduled report happens, the next night's answer names it as the recent one with the same period and it stays **one lead** with a new observation (`reported`), not a second lead.
  - A missing or unparseable date skips that event, not the row or the job.
- The event key: `(symbol, period end)`, e.g. `NASDAQ:LITE:2026-09-30`, so a moved date or a new status is a new observation of the same lead (the existing insert-only observation path in `atlas.tradingview.schedule`). The lead's title names the period ("Lumentum results, quarter ending 30 Sep 2026" or similar).
- Kept from each row: symbol, the two dates, `next_date_confirmed`, `fiscal_period_end`. **Never named by the model or stored:** `close` (a price: the owner allows prices only for settlement and replays, through `tradingview_prices`, never through the calendar), `release_next_time_flag` and `publication_type_next_fq` (meaning unconfirmed), `release_next_at`, `name`, `description`, and every consensus or estimate key. Check `_Model` ignores unknown fields (`extra="ignore"`).
- Symbols asked for but absent from the answer are no error (IQE, Soitec, Innolight today); the existing guard "no item names a symbol asked for" stays.
- The old guessed shape (`items: [{id, symbol, fiscal_period, fiscal_year, date, status}]`) is dropped, its fixtures replaced. Update the module docstring's shape list and `docs/decisions.md` ("The TradingView override, extended for the agents": the calendar's shape confirmed on 2026-10-16 from the live answer; what is kept and what is dropped; the derived period of the recent report).
- Fixtures under `tests/fixtures/tradingview/` in the confirmed shape (values synthetic, labelled so in `_fixture` and the manifest): Lumentum with a recent and a next report; the same a week later with the next date moved and confirmed; the same after the report (the former next now `release_date`, a new next quarter); a row carrying `close` and a made-up consensus key (`eps_estimate_next_fq`) that must not be stored; a symbol asked for that the answer leaves out.

## Acceptance criteria

- [x] HTTP-seam tests against the TradingView fake (the job through the queue, read through `GET /api/v1/leads?origin=tradingview_calendar`): two leads per row (recent `reported`, next `scheduled`/`confirmed`) with the right dates and periods; a moved and confirmed next date adds an observation to the same lead; after the report the former next lead gains a `reported` observation and no second lead appears for that quarter; `close` and the consensus key appear nowhere in the stored leads, observations or job artifacts; an absent symbol is no failure; an answer without `data.earnings` fails with `unparsed_answer`.
- [x] `upcoming_reports` (the MCP tool) lists the next reports from the new leads (its existing test updated to the new fixtures).
- [ ] Ruff, strict pyright, the unit and integration suites green.
- [ ] (The lead) the next nightly job on production after deploy succeeds with leads for the nine symbols.
