# 17: News stories through TradingView, in the ledger

**What to build:** For every universe company, the news stories TradingView lists are in the archive with their text, as Tier C Source Versions: who published them, when, which companies they name, and the owner's override on each. Innolight, whose exchange filings Atlas may not fetch, gets its first archived material this way.

The owner's decision (2026-10-02), after the lead reported that Innolight has nothing in Memory and named manual imports or an exchange licence as the ways out: "We can use tradingview for news, probably easier then other services you mentioned. I'll leave for you to build this out." This widens the 2026-09-30 override from news headlines to news story text. Everything else the override says stands: off by default, every stored item marked, paced, nothing real committed to git.

What exists: `tradingview_catalog` stores each company's headlines as Tier C leads (origin `tradingview_news`, 432 on production, about 50 for Innolight; publishers Dow Jones Newswires, Reuters, Zacks, GlobeNewswire and others) and never fetches story text. The cluster's proxy allows the tool `mcp-tv-get-news-story` (home-ops `kubernetes/apps/llm/toolhive/tradingview-mcp/mcptoolconfig.yaml`); Atlas's client has no code path for it.

- **A fourth tool.** The client gains `mcp-tv-get-news-story`, bounded and recorded like the other three (the per-job call cap, the `tradingview` budget, a `tradingview_request` row per call). Its answer's shape is not recorded anywhere yet: write the model to tolerate unknown fields, keep the raw answer as the raw bytes, and say in the log that the shape is from the tool's schema, not from a live call. The lead makes the first live call after deploy and files what differs.
- **A `tradingview_news` job** (not pausable, like the other TradingView jobs; enqueued by `tradingview_catalog` after it stores headlines): for a company's headlines without a stored story, newest first, at most `ATLAS_TRADINGVIEW_MAX_STORIES_PER_JOB` (default 10), fetch the story and record it.
- **A story is a Tier C Source Document:** provider `tradingview`, source type `news`, publisher `<publisher> via TradingView`, licence class `licensed:tradingview-owner-override`, the override text in its metadata, `available_at` the story's published time (`publisher_timestamp`), the companies it names from the headline's related symbols mapped to universe companies. The Source Document belongs to the company the headline was listed for; the other named companies are in its metadata. Parsed by a small parser (`tradingview-news-v1`: the story's paragraphs as text, title first).
- **Wire copies are one family.** The same story from two publishers, or re-listed for two companies, falls into one Evidence Family by the existing rule; a story already archived for another company is linked, not fetched again (the headline ID).
- **Nothing downstream changes in this ticket.** A news Source Version is not triaged, not retained, not offered to an Investigator or the Skeptic, and can never make an Assertion: ticket 18 decides what Memory and an investigation do with it. `atlas ingest`, passage selection and `extract_claims` skip source type `news`; a test holds that.
- The lead headline's row links to its Source Version; `GET /api/v1/leads` shows it; the source viewer opens it, marked Tier C.
- Fixtures are synthetic (`tests/fixtures/tradingview/`), as the override requires. `docs/decisions.md`: "News stories through TradingView" with the owner's words; `docs/source-licenses.md` and the site or source register entry; `docs/runbooks.md`, "TradingView (owner override)".

Migration revision `0068` (down: main's head).

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] Integration test at the worker seam with the TradingView fake: a catalog job stores two headlines and enqueues the news job; the news job fetches both stories within its cap, each a Tier C Source Version with publisher, published time, override text and named companies; a rerun fetches nothing.
- [ ] A story listed for two companies is fetched once and linked; two publishers' copies of one text share an Evidence Family.
- [ ] The cap and the budget hold: a third story beyond the cap waits for the next job; a spent budget fails the job without a request.
- [ ] With TradingView disabled the job fails at once without a request.
- [ ] `extract_claims` given a news Source Version refuses it; passage selection never offers one; no Assertion can be created on one (API test).
- [ ] The lead read and the source viewer show the story as Tier C (API client regenerated; frontend unit test of the pure part).
- [ ] Decision, licence, runbook entries; `AGENTS.md` line.
