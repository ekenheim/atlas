# Scorecard coverage plan (ticket 29, order step 2)

Written 2026-10-18 by the lead, before any code reading or session, from `docs/research/early-signal-case-studies.md`. For each case and as-of date, the documents the key's cue depends on. After the nightly ingest and the TradingView catalog have run for the case's company, each row is checked against the production archive (`GET /api/v1/companies/{id}/dossier` sources, by `available_at` <= the as-of date) and marked **present** or **absent**. An absent key document is recorded as miss class **M1** (intake) for that run *before* any session; the session still runs.

Dates marked *(case study)* are from the case-study tables; the others are the company's regular reporting rhythm, to be confirmed from the catalog, not assumed.

| Case | As-of | Key documents that must be public by the as-of date | Source path | Present? |
|---|---|---|---|---|
| SanDisk | 2025-02-28 | Investor Day 2025-02-11 transcript *(case study)*; Form 10 / spin-off 8-Ks (context) | TradingView; SEC | |
| SanDisk | 2025-05-31 | + Q3 FY25 call 2025-05-07 *(case study)*; Q3 FY25 10-Q | TradingView; SEC | |
| SanDisk | 2025-08-31 | + Mizuho conference 2025-06-11 *(case study)*; Q4 FY25 call 2025-08-14 *(case study)*; FY25 10-K (filed about late Aug 2025) | TradingView; SEC | |
| IREN | 2025-03-31 | Q2 FY25 call 2025-02-12 *(case study: "the escalating power shortage", 2.3 GW held)*; 6-K results | TradingView; SEC | |
| IREN | 2025-05-31 | + Q3 FY25 call 2025-05-14 *(case study: "That is the critical bottleneck")*; 6-K results | TradingView; SEC | |
| AXT (calibration) | 2025-08-31 | Q2 2025 call 2025-07-31 (in the archive since pilot-review ticket 26); Q2 10-Q | TradingView; SEC | |
| eToro | 2025-09-30 | F-1 (spring 2025); Q2 2025 call 2025-08-12 *(case study)*; 6-K results | SEC; TradingView | |
| Snap | 2025-08-31 | Calls 2025-02-04 *(case study)*, Q1 2025 (late Apr), Q2 2025 (early Aug); 10-K FY2024, 10-Qs | TradingView; SEC | |
| POET | 2025-11-30 | Call 2024-11-14 *(case study)*; 20-F FY2024 (spring 2025); quarterly calls/6-Ks through Q3 2025 (Nov 2025); AGM | TradingView; SEC | |
| Raspberry Pi | 2025-10-31 | Interim results call 2025-09-23 *(case study)*; RNS interim results | TradingView (call); FCA NSM (no adapter configured: reported **not run** unless imported) | |

Rules for filling the last column:
- A document counts as present only if its Source Version's effective `available_at` is on or before the as-of date (the session cannot see it otherwise).
- A transcript the catalog lists but has not yet fetched is **pending**, not absent; the run waits for it, or the reason it was not waited for is written here.
- Record the check's date and the archive counts per company beside the table when it is filled.
