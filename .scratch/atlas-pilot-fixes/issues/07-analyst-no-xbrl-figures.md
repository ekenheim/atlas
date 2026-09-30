# 07: The Financial Analyst received no XBRL figure

**What to build:** In pilot investigation 1's re-run (0.2.3), every scenario input the Financial Analyst proposed for Lumentum and Coherent is `missing` with the reason "No XBRL figure supplied", although both companies' companyfacts are normalized in production (`GET /api/v1/companies/{id}/financials?as_of=` returns figures). Diagnose whether the Analyst's context (`scenarios/analyst.py`) selected figures as of the investigation's `as_of`, sent them under the metric names the prompt expects, or dropped them (currency, unit or period filters); role call `2150b97c-19db-4868-b9b4-860e3616da0a`. Fix so that reported revenue, operating margin, cash, debt and diluted shares arrive as `sourced` inputs when the observations exist.

**Blocked by:** None

**Status:** needs-triage

- [ ] The cause is recorded in the ticket with the production run's evidence.
- [ ] An integration test at the investigation seam: with the Lumentum EDGAR fixtures' companyfacts, the Analyst's request carries the as-of figures and its proposal marks them `sourced`.
