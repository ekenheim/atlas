# XBRL companyfacts normalization for as-of financials

Type: research
Status: resolved
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

## Answer

Full findings: `docs/research/xbrl-normalization.md` on branch `research/xbrl-normalization` (`bc25fa6`). 6 SEC requests.

- **Filers:** STMicroelectronics files its 20-F under **US GAAP in USD**, so the IFRS example is Nokia (`ifrs-full`, EUR).
- **companyfacts drops segment, product and geography facts and custom tags.** Lumentum's Components/Systems split (and STM capex since 2010) aren't there, so product-level exposure must come from filing text (Assertions), not XBRL.
- **Tags drift:** Lumentum's revenue has used 4 different tags over time, so a per-concept tag list with precedence is needed. `ShortTermBorrowings` duplicates `LongTermDebtCurrent`, so summing debt tags double-counts.
- **`fy`/`fp` belong to the filing, not the fact; `frame` marks the latest filing.** Using `frame` for as-of views leaks the future.
- **Restatements:** Nokia's FY2023 revenue went 22,258M → 21,138M. A mis-tag (an EPS of 3.29) looks like a restatement, so the rule adds a suspect flag.
- **As-of rule:** select per (concept, period, unit) from the latest filing whose `available_at ≤ as_of`. A fact's `available_at` is its filing's acceptance time, never the companyfacts fetch time. Worked examples in the doc (Q4 = FY − 9M, which reconciles to the release's $1,006.3M).
- **Calendar:** Lumentum's FY2027 is a 53-week year.
- **Fixture:** the current one lacks the FY2026 revenue tag, capex, debt and diluted shares, so it must be re-trimmed before Phase 5.
- **Temporal-integrity finding for shipped Phase 1 code:** EDGAR holds filings accepted after 17:30 ET until the next business day. `available_at = acceptanceDateTime` is too early for those (every recent Lumentum 10-Q) → **fix ticket 10**.
