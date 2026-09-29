# Entity-resolution sources: SEC tickers, GLEIF, OpenFIGI

Type: research
Status: resolved
Blocked by: none

## Question

For SEC `company_tickers.json`/`company_tickers_exchange.json`, the GLEIF API and OpenFIGI (keyless):
- endpoints and response shapes
- rate limits and terms for automated use
- what each can match (name, ISIN, ticker+MIC, LEI, CIK)
- how to represent effective-dated tickers and ADRs/multiple listings in the §5.1 `security` table
- what a deterministic resolution pipeline looks like, and which cases remain for human review

## Context

Research in progress on branch `research/identity-apis`; findings in `docs/research/identity-apis.md` on that branch.

## Answer

Full findings: `docs/research/identity-apis.md` on branch `research/identity-apis` (`5aba8ee`). Built from live calls: SEC ~12, GLEIF 10, OpenFIGI 6 (keyless).

- **No source links CIK to LEI.** The SEC submissions `lei` field is null for Lumentum and Coherent. The link is made on name plus jurisdiction, and a reviewer checks it once per company.
- **GLEIF:** an ADR's ISIN maps to the underlying issuer (TSM → TSMC). `fuzzycompletions` is unreliable (empty for Lumentum). Full-text search returns the parent plus its subsidiaries. Coherent's LEI is LAPSED but still identifies it. The data is CC0; 60 requests/min.
- **OpenFIGI:** needs the operating segment MIC (`XNGS`, not `XNAS`). An old FIGI survives renames (the II-VI FIGI still resolves to COHR), but there's no ticker history (IIVI isn't found). 25 requests/min (search 5/min); FIGIs are public domain.
- **SEC:** 10 requests/s; the `exchange` field is only a label; the ticker files carry no accuracy guarantee.
- **Proposed pipeline:** four tiers (exact, corroborated, candidate, conflict). A name-only match is never committed.
- **Schema gaps (8):** FIGI level; ADR link and ratio; operating vs segment MIC; where each mapping came from; review state on `security`; an alias table; uniqueness; currency.
- **Fixtures:** 13 sets named for recording.
