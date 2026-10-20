# The quotes checked against their sources

Type: task
Status: needs-info
Blocked by: 01, and the owner's answer to the spec's open question 1

## What to build

### The job

A `verify_quotes` job runs for each stored theme edition. It makes no LLM call and is not pausable.

It works over the edition's `primary_sources`, deduplicated by (URL, quote) across editions and themes, because the council and later editions reuse quotes.

### Fetching

- Each URL is fetched at most once a week, through the fetch gate (`ledger/web_fetch.py` and the site register).
- The page is archived as a Source Version with `provider: cited`. A PDF is parsed like any other document.

### Locating the quote

The quote is located in the parsed text with the typographic fold (`atlas.mcp.locate`):
- A match after normalising and collapsing whitespace counts.
- An ellipsis splits a quote into parts, which must all occur, in order.
- A non-English quote is located as written.

### The result

One insert-only `quote_check` row per (edition, source), with one of three results:
- `verified`: the quote was found. The row records the Source Version and the span.
- `not_found`: the page was read and the quote is not in it.
- `unreachable`: the page could not be read. The row gives the reason: `forbidden`, `unchecked_site`, `robots`, `error` or `paywall`.

The row also records the tier of what was read, from a small host map in config:
- `issuer`: the company's or regulator's own site, an exchange filing, or EDGAR;
- `third_party_transcript`: fool.com, investing.com, webull.com, gloom.sh and the like;
- `press`;
- `other`.

### The council

The council's board items are linked to the theme quotes their IDs cite. The council's own quotes (nine in edition 2) are only in its page's prose, not in its ledger. If the owner adds the proposed prompt line, they arrive as the council ledger's `primary_sources` and are checked like a theme's. Until then they are not checked, and the page says so.

### Reads

- `GET /api/v1/editions/{id}/quotes`;
- counts per edition: verified, not found, unreachable by reason, and by tier;
- the metric `atlas_quote_checks_total{result,tier}`.

## The decision this waits on

The site register lists few of the cited hosts.

The recommendation to the owner:
- Allow a verify-only fetch of a cited URL when the site's terms are silent or permit personal use, as under the 2026-10-19 override.
- Obey robots.txt and make one request per document.
- `forbidden` stays forbidden.

Each unchecked site then needs its terms read once. The job lists the unchecked hosts so the lead can work through them.

## Tests

- The fixtures' quotes are checked against recorded copies of a few cited pages: an EDGAR exhibit, a PDF and a transcript page, giving one result of each kind.
- The deduplication.
- The tier map.

## Done when

- [ ] The 2026-10-19 editions are checked on production.
- [ ] The lead has read the quotes found `not_found` and reported them.
