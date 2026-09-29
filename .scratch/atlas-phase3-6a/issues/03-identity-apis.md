# Entity-resolution sources: SEC tickers, GLEIF, OpenFIGI

Type: research
Status: claimed
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
