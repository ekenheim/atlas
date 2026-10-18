# Bottleneck scan, 2026-10-18 (ticket 33)

A market-wide search of SEC filings for supply-constraint language: the first scan of Atlas's own find step. This "Method" section was committed before the scan ran. The results below it were added after.

## Method (fixed before the run)

**Source.** The EDGAR full-text search API (`efts.sec.gov/LATEST/search-index`), every filer.
- **Forms:** 10-Q, 10-K, 8-K, 6-K, 20-F and 40-F, exhibits included (an 8-K's EX-99 press release or call transcript is searched too).
- **Filed:** 2026-06-20 to 2026-10-18 (120 days).
- **Requests:** Atlas's SEC user agent, at most 5 a second.

**Phrases.** Each one is an exact-phrase query. "Strong" phrases state a constraint in progress, "medium" ones its usual signs, and "weak" ones are often boilerplate.

- **Strong (1.0):**
  - "demand exceeds supply", "demand exceeded supply", "demand continues to exceed supply";
  - "demand outpaces supply", "demand outpaced supply", "demand outstrips supply";
  - "undersupplied", "supply shortage", "supply shortages";
  - "capacity constrained", "capacity-constrained", "sold out", "fully booked", "on allocation";
  - "unable to meet demand", "unable to keep up with demand", "cannot get enough";
  - "supply remains tight", "tight supply".
- **Medium (0.5):** "extended lead times", "lead times have extended", "lead times have increased", "longer lead times", "record backlog", "pricing power", "raised prices".
- **Weak (0.25):** "sole source", "single source", "limited number of suppliers", "shortage of".

**Exclusions.**
- **The universe:** every `cik:` in `configs/themes/ai-infrastructure.yaml`, scorecard cases included.
- **Finance, insurance and real estate:** SIC 6000–6799, where "tight" and "shortage" usually mean liquidity or housing. Blank-check companies (6770) are in this range.
- **Funds and trusts:** filers with no SIC.

**Score and shortlist.**
- **Score:** a filer's score is the sum of the weights of the distinct phrases its filings matched. Several filings matching the same phrase count it once.
- **Ranking:** by score, ties by the most recent matching filing. The top 40 go to the analyst.
- **Passages:** for each shortlisted filer, up to six passages of about 800 characters around a matched phrase, strongest phrase first and newest filing first, taken from the filing documents themselves.

**The analyst's reading.**
- **Who reads:** one Opus reader, who sees the passages, the filer's name, SIC and form, and no prices. It classes each filer:
  - **holder:** the company controls the scarce thing: its own capacity sold out, its product on allocation, its prices rising on demand;
  - **squeezed:** it buys a scarce input;
  - **noise:** risk-factor boilerplate, a hypothetical, a past episode, a company-specific failure, or a shortage of labour or housing unrelated to supply;
  - **unclear.**

  Each class comes with the quote that decides it, what is scarce, and whether other shortlisted filers point at the same scarce thing (a cluster).
- **A second, blind reader** classes the same 40 for the precision@20 measure. Where the two disagree, the lead decides.

**Known limits, stated before the run.**
- Filings miss calls and conferences.
- Exact phrases miss paraphrase.
- Large filers write the same risk language every quarter, so the weak phrases are boilerplate-prone. That is why they weigh a quarter.
- The full-text search covers filings from 2001 on, but only the 120-day window is read here.
