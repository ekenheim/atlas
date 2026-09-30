# 12: EDGAR full-text search as a discovery channel

**What to build:** Web discovery through the owner's SearXNG returns nothing usable. Probed on 2026-09-30 with the pilot query "InP wafer substrate supplier capacity EML laser": Bing answers with results unrelated to the query (Swedish news, Swedish health-portal logins, YouTube help) for `language` en, en-US, en-GB and all alike; Brave "too many requests"; DuckDuckGo CAPTCHA; Startpage and Qwant parsing errors; Mojeek and Presearch access denied; Google, Yahoo and Wikipedia no results. Pilot fix 08's ranking v2 rightly keeps none of it. SEC EDGAR full-text search (`https://efts.sec.gov/LATEST/search-index?q=...&forms=...&dateRange=custom&startdt=&enddt=`, keyless, SEC's fair-access rules: the SEC User-Agent and ≤ 10 requests/s, which Atlas's SEC client already enforces) answers the same research need from primary sources: `"InP substrates"` in 10-Ks filed 2025-06-01 to 2026-09-30 returns AXT (10-K 2026-03-17), Aeluma (10-K 2026-09-16 and 2025-09-09) and Coherent (10-K 2026-08-14).

Build a second discovery channel beside SearXNG:
1. **An EDGAR full-text search client** in `atlas.sources` (or `atlas.discovery`) through the existing SEC HTTP client (rate limit, User-Agent, retries), with a recorded-fixture fake for tests. The response shape is documented in SEC's EDGAR full-text search FAQ; record the fields used (`hits.hits[]._source`: `ciks`, `display_names`, `form`, `file_date`, `adsh`, the document id in `_id`), and cite the page in the decision entry rather than calling it in tests.
2. **The Scout's queries go to both channels.** EDGAR gets the query's key phrase(s) (the Scout's schema may gain an optional `filing_phrase`, the exact phrase to search in filings, e.g. `"InP substrates"`, `"sole source"` + product; prompt `scout.v3`), forms 10-K, 10-Q, 8-K, 20-F, 6-K, 40-F, and the investigation's as-of window (default: the 18 months before `as_of`). Each hit becomes a **lead** whose `origin` is `edgar_fts`, canonical URL the filing document's SEC URL, title "<filer> <form> filed <date>", with the filer's CIK. Ranking (fix 08's v2) applies; a filing hit from EDGAR is not demoted as a company's own page.
3. **A hit from a universe company** is a pointer to a document Atlas can ingest: if the filing's Source Version isn't archived, the lead records that (`ingestable: true`), and the Investigator's document choice is unchanged in this ticket (it reads the archive). **A hit from a filer outside the universe** feeds `propose_candidates` directly with its CIK (no name resolution needed): Aeluma above would become a Candidate.
4. The Skeptic's searches use the same two channels.
5. Settings: `ATLAS_DISCOVERY_EDGAR_FTS` (`on` by default when `ATLAS_SEC_USER_AGENT` is set), `ATLAS_DISCOVERY_EDGAR_MAX_HITS` per query (default 10). Leads keep being Tier C metadata, never Evidence.

**Blocked by:** None

**Status:** done

- [x] Integration test at the investigation seam with the EDGAR FTS fake: a Scout query yields `edgar_fts` leads with filer, form and date; a hit from a filer outside the universe proposes a Candidate keyed by its CIK; SearXNG returning nothing doesn't stop the investigation.
- [x] Unit tests of the client's request (phrase quoting, forms, date range, User-Agent) and parsing from a recorded-shape fixture.
- [x] Decision entry (why a primary-source channel; the SearXNG probe as evidence), AGENTS.md line, `docs/runbooks.md` note that the SearXNG instance's engines need the owner's attention.
