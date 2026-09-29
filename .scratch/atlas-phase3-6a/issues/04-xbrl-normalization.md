# XBRL companyfacts normalization for as-of financials

Type: research
Status: claimed
Blocked by: none

## Question

Using Lumentum's archived companyfacts and one IFRS 20-F filer's (STMicroelectronics if it files XBRL):
- which concepts matter for exposure/scenario work (revenue, segment revenue if tagged, gross margin, capex, inventories, shares outstanding, debt)
- duplicates across filings and how restatements appear
- how to select the value per (concept, period, unit) from the latest filing with available_at ≤ as_of (spec §5.7)
- units and currency; fiscal calendars (Lumentum's 52/53-week year)
- what's missing that the scenario model needs

Cite SEC and FASB/IFRS taxonomy sources.

## Context

Research in progress on branch `research/xbrl-normalization`; findings in `docs/research/xbrl-normalization.md` on that branch.
