# Source entitlements

The entitlement inventory: which sources Atlas may fetch, archive, send to a hosted LLM and commit as fixtures, and on what basis. A source that isn't listed here as allowed is not used. Adding or changing a row is a reviewed commit, made before the adapter that uses it.

Sources:

- the product spec [`hindsight_investment_research_build_plan.md`](../hindsight_investment_research_build_plan.md) §1.4 (no circumvention of paid entitlements, no scraping against terms), §4.1 (source tiers), §4.2 (adapters), §4.3 (licensed text and third-party LLMs), §9.3 (the market-data decision gate), §12 (each provider documents its entitlements) and §16 (unlicensed crawling risk)
- the pilot spec [`.scratch/atlas-pilot/spec.md`](../.scratch/atlas-pilot/spec.md): Part A stories 18–19 and the "Phase 0 source-entitlement inventory and threat model inputs" note
- ticket 12's findings: `docs/research/serenity-skills-alignment.md` (on the `research/serenity-skills-alignment` branch), data sources D1–D7 and recommendation R3
- [ADR-0002](adr/0002-fresh-edgar-adapter-sibling-repos-reference-only.md) (sibling repositories' data is not an Atlas entitlement) and [`threat-model.md`](threat-model.md) (T18–T20)

Terms follow [`CONTEXT.md`](../CONTEXT.md). This is Atlas's working assessment for a single-user, private research tool, not legal advice. Re-check a source's terms when its adapter is built and record the date.

## 1. Statuses

| Status | Meaning |
|---|---|
| **allowed** | May be fetched by an adapter under the stated conditions, archived as Source Versions and used as Evidence |
| **lead-only** | May suggest questions and URLs. Never Evidence on its own (build plan §4.1 Tier C). What it points to becomes Evidence only by being fetched under its own **allowed** row |
| **unlicensed** | Never fetched, scraped, archived, retained into Hindsight or committed. No Source Document is created for it |
| **absent** | No provider exists. Coverage is shown as absent, never filled with synthetic facts (build plan §4.2, §16) |

## 2. License classes

Every `source_document` row carries one `license_class` ([`data-model.md`](data-model.md) §2.3). The source ledger refuses to archive a class whose "Archive" column says no.

| `license_class` | Covers | Archive raw bytes | Retain into Hindsight (hosted LLM) | Commit as a fixture |
|---|---|---|---|---|
| `public_regulatory` | Regulator-published disclosures (SEC EDGAR) | Yes | Yes | Small, trimmed recorded responses only |
| `public_issuer` | Issuer-published public material fetched under robots.txt and site terms (IR releases, presentations, annual reports) | Yes, unless the site's terms forbid storage | Yes, unless the site's terms forbid automated or AI processing (recorded per site in §5) | No; use synthetic equivalents |
| `lead_metadata` | Discovery responses: query, engines, URLs, titles, snippets, response metadata | The response metadata only | No (leads aren't retained as Memory) | Synthetic only |
| `manual_lead` | A single public item entered by hand as a lead, for example one social post's URL with the researcher's note | The URL and note only; the content isn't fetched | No | No |
| `synthetic_fixture` | Documents written for tests and gold cases (fictional companies) | Yes | Yes (recorded, in the spike and live tests) | Yes |
| `licensed:<provider>` | Reserved for a future provider with a recorded agreement | Per agreement | Only after the provider's terms and the LLM provider's data policy are checked (build plan §4.3) | Never full text |

No `licensed:*` class is in use: Atlas has no paid data provider.

## 3. Inventory

### 3.1 Allowed

| Source | Tier | `license_class` | Basis | Conditions | Phase / adapter |
|---|---|---|---|---|---|
| **SEC EDGAR**: submissions index (`data.sec.gov/submissions`), filing documents (`www.sec.gov/Archives/edgar/data/…`), XBRL `companyfacts` (`data.sec.gov/api/xbrl/companyfacts`), official bulk files | A | `public_regulatory` | Public regulatory disclosures, accessed under SEC's fair-access policy (<https://www.sec.gov/os/accessing-edgar-data>) | A declared User-Agent with a name and contact, set in env (`SEC_USER_AGENT`), never committed. One shared limiter at ≤10 requests per second across all jobs. Backoff honoring Retry-After. Conditional requests where supported. Server-side only (no CORS). Bulk files for history. `available_at` from `acceptanceDateTime` | 1 / ticket 06 |
| **Company investor relations**: public releases, presentations, legitimately accessible annual and interim reports; official customer/supplier disclosures | A | `public_issuer` | Public issuer publications, fetched politely under each site's terms | Honor robots.txt, site terms and rate limits. Record which gate allowed each fetch (build plan §4.2). Each site is onboarded in §5 before its first fetch | 3 |
| **Exchange and regulatory notices outside the US**, where a source-specific adapter exists | A | `public_regulatory` | Per regulator | Same as IR: onboard each regulator in §5 first. Until then non-US coverage is **absent** | 3+ |
| **HKEXnews** (HKEX's disclosure site): the title search (`www1.hkexnews.hk/search/titleSearchServlet.do`) and the documents it links (`/listedco/listconews/…`) | A | `public_regulatory` | **Blocked for automation**: HKEX's Terms of Use forbid robots, scrapers, text and data mining and systematic retrieval into databases; the automated route is the licensed IIS feed or HKEX's written consent (§5 below) | Every request passes the fetch gate, which blocks HKEXnews (an ingest records a `blocked` gate decision and fetches nothing) until an IIS licence or consent is recorded in `configs/sources/sites.yaml`. Documents the owner downloads by hand come in through `atlas sources import` (provider `manual_import`). The adapter is built and fixture-tested for that day. `available_at` from the listed `DATE_TIME` (Hong Kong time), basis `publisher_timestamp`. robots.txt read and obeyed (it serves none today) | 3 / ticket 04 |
| **FCA National Storage Mechanism** (the UK's archive of regulated information): the search API (`api.data.fca.org.uk/search?index=nsm-search`) and the documents it links (`data.fca.org.uk/artefacts/NSM/…`) | A | `public_regulatory` | Terms of Use: use "for any lawful purpose" subject to the Acceptable Use Policy (no reproducing or reselling the site, no disruption, no use of the FCA's marks) (§5 below) | IQE (`exchange:fca-nsm`). Every request passes the fetch gate; 0.5 requests/s live. Only the issuer's own disclosures (its LEI as disclosing organisation); `available_at` from `publication_date`, else `submitted_date` (UTC), basis `publisher_timestamp`. robots.txt read and obeyed (it serves none today) | 3 / ticket 05 |
| **LSE RNS** (`www.londonstockexchange.com` news pages) | A | `public_regulatory` | **Blocked**: robots.txt disallows `/en-gb/`; the disclaimer limits storage to personal use off any network (§5 below) | The gate blocks it; IQE's announcements come from the NSM | ticket 05 |
| **AMF info-financière** (France's regulated-information database, run by the DILA): the documented Explore API v2.0 records of dataset `flux-amf-new-prod` (`www.info-financiere.gouv.fr/api/explore/v2.0/…`) and the files they link (`fr.ftp.opendatasoft.com/datadila/INFOFI/…`) | A | `public_regulatory` | Licence Ouverte / Open Licence 2.0 (Etalab); 10,000 API calls per IP per day (§5 below) | Soitec (`exchange:amf`). The documented API only, never the site's pages or RSS/Atom feeds; ≤ 10 API calls per discovery; 0.5 requests/s live; each document credits the AMF, the dataset, the record's last update and the licence (`attribution`). `available_at` from the later of `uin_dat_amf` and `informationdeposee_inf_dat_emt` (UTC), basis `publisher_timestamp`. The feed's language decides retention (French archived, not retained). robots.txt read and recorded; not obeyed for the API client's URLs (it addresses crawlers) | 3 / ticket 06 |
| **Euronext** (`www.euronext.com`, `live.euronext.com` company news) | A | `public_regulatory` | **Blocked**: the Terms of Use prohibit robots, spiders and systematic retrieval without prior written permission (§5 below) | The gate blocks it; Soitec's regulated information comes from the AMF API | ticket 06 |
| **soitec.com** | A | `public_issuer` | **Blocked**: its terms forbid using or copying the site's elements without Soitec's prior written permission (§5 below) | The gate blocks it | ticket 06 |
| **Tier B public material**: patents, formal technical papers, official statistics, trade-association datasets, public conference materials | B | `public_issuer` | Public and distributable | Only when public and distributable; onboard each source in §5 | 3+ |

EDGAR also hosts 13F, Form 4 and S-3/424B filings. They are allowed as sources on the same terms, but holdings and insider-flow analysis is out of scope (build plan §1.4). S-3/424B dilution terms are a Phase 5 falsifier candidate (ticket 12, M6), so the EDGAR form filter is configurable.

### 3.2 Lead-only

| Source | Tier | `license_class` | Conditions | Phase |
|---|---|---|---|---|
| **SearXNG** (the cluster's `llm/searxng`, JSON API, no key) | C | `lead_metadata` | The default live discovery provider. Record the query, the engines named explicitly, `unresponsive_engines`, response metadata and the discovery date. SearXNG queries public search engines on Atlas's behalf, so keep volume low under a per-provider budget. A snippet never supports an Assertion | 3 |
| **Exa** (optional) | C | `lead_metadata` | Disabled until a key exists (`<provider> disabled: missing EXA_API_KEY`). Not currently entitled. If it needs a paid plan, flag it to the owner first (no pay-as-you-go) | 3, optional |
| **Individual public social posts** (X and similar) | C | `manual_lead` | Entered by hand as one URL plus the researcher's note. Never scraped or bulk-collected; content isn't archived. One author's repeated posts are one Evidence Family | 3 |
| **General news, blogs, vendor marketing, search snippets** | C | `lead_metadata`, or `public_issuer` once the site is onboarded in §5 | Leads only. They can't establish a customer contract, a Bottleneck or revenue exposure on their own (build plan §4.1) | 3 |

### 3.3 Unlicensed

None of these is fetched, scraped, archived, retained into Hindsight or committed.

| Source | Why | Notes |
|---|---|---|
| **Social and X archives**: bulk tweet archives, X Articles, the serenity-aleabitoreddit corpus, collection through `xreach`, `twitter-cli`, x.com profile HTML or the `r.jina.ai` proxy | No licence; collected by scraping fallbacks and authenticated fetches that conflict with "no scraping that violates source terms" (build plan §1.4) | Ticket 12, D3 |
| **The serenity-aleabitoreddit skill repository** (`yan-labs/serenity-aleabitoreddit`) | No licence file at commit `20e9e90` (GitHub reports `license: null`), so all rights are reserved. It also carries an agent auto-update instruction | Its method is recorded as findings. Its text, templates and data are never vendored, ingested, redistributed or installed as a skill ([`threat-model.md`](threat-model.md) T4) |
| **LinkedIn**: job postings, profiles, company pages | The site's terms forbid scraping | Ticket 12, D4 |
| **Paywalled and licensed datasets**: SMM spot prices, TrendForce, Digitimes, paywalled memory-pricing reports, sell-side research notes (for example Citi, Goldman Sachs, Nomura), customs and import logs (bills of lading), earnings-call transcripts, consensus estimates, global supplier databases | Not entitled; paid or licensed | A sell-side figure cited second-hand in a public document is at most a `third_party_report` Assertion on that public document. Coverage is **absent** (build plan §4.2) |
| **Yahoo Finance prices** (including `yfinance`) | Unofficial API, no licence for this use, opaque adjustment and no point-in-time history | Ticket 12, D7 |
| **Options data, short interest and borrow, dark-pool and block flow, Polymarket odds** | Unlicensed, and they serve trading lenses Atlas excludes (build plan §1.4) | Ticket 12, D7 |
| **Data held by sibling repositories** (`trading-research`, `alphaos`, `TradingDashboard`): their market-data buckets and caches, unofficial feeds and personal portfolio records | Not an Atlas entitlement. Their price data comes from a personal subscription whose terms were not assessed for Atlas, and from unofficial feeds | ADR-0002 |

### 3.4 Absent

| Capability | State | What unblocks it |
|---|---|---|
| **Market data (prices, corporate actions, delistings)** | **No market-data provider.** Paper tracking records Research Snapshots and fundamental outcomes only; return metrics show "no market data provider" | The §9.3 decision gate before Phase 6: choose a provider, record its licence and coverage (including the non-US names) here, and put it behind the adapter and fixture pattern |
| **Firecrawl** | Deferred, not entitled | Only for dynamic sites where plain HTTP collectors fail; record terms and costs first |
| **OpenBB** | Phase 5+, optional | Only installed, supported providers; log each underlying provider's entitlement and licence |
| **Transcripts, consensus, supplier databases** | Absent | A licensed provider, recorded here as `licensed:<provider>` |

## 4. Processors: where source text goes

These receive source text but are not sources. Build plan §4.3 counts Hindsight's extraction LLM as a third-party provider when it points at a hosted model, which it does.

| Processor | Receives | Allowed classes |
|---|---|---|
| **Atlas Hindsight** (dedicated, in-cluster) | Parsed sections of retained Source Versions; stores extracted facts and chunks in its own database | `public_regulatory`, `public_issuer` (where the site allows), `synthetic_fixture` |
| **LiteLLM → MiniMax-M3** (`atlas-extract`, `atlas-reflect`; a hosted third party) | Hindsight's extraction and reflect prompts, which contain source text | The same as Hindsight. Never a `licensed:*` class without checking the provider's terms and MiniMax's data policy |
| **LiteLLM embeddings and rerank** (`qwen3-embedding-0.6b`, `rerank`) | Chunks and queries | The same as Hindsight |

## 5. Site and provider register

Per-site onboarding for `public_issuer` and non-US `public_regulatory` sources. A row is added before the first fetch, with the terms URL, the date checked, robots.txt status, the rate budget and the decision on archiving and LLM processing. The machine-readable copy is the site register, `configs/sources/sites.yaml`: the fetch gate (`atlas.sources.gate`) blocks any host not in it, any site whose terms forbid automation without a recorded consent, and any site whose terms are unchecked, before making a request. Lumentum's and Coherent's IR sites are onboarded with the Company IR adapter in Phase 3.

| Site or provider | Terms checked (URL, date) | robots.txt | Rate budget | Archive | Hosted LLM | Decision by |
|---|---|---|---|---|---|---|
| HKEXnews (`www1.hkexnews.hk`, `www.hkexnews.hk`, `www2.hkexnews.hk`) | <https://www.hkex.com.hk/Global/Exchange/Terms-of-Use?sc_lang=en> (updated 19 Aug 2025, covering hkexnews.hk), checked 2026-09-29: forbids "any 'robot', 'bot', 'spider', 'scraper' or other automated device … to access, obtain, copy, monitor or republish any portion of the Website", text and data mining and web scraping "for any purpose", including AI training, and compiling databases by systematic retrieval; the official automated route is the licensed Issuer Information feed Service (IIS); HKEX's prior written consent (info@hkex.com.hk) also lifts a restriction | None (404) | 1 request/s | Only documents the owner fetched by hand and imported (`atlas sources import`) | English imports are retained | **Blocked** (`automation: forbidden`, reason "blocked: HKEX Terms of Use prohibit automated access (IIS licence or written consent required)"): lead, 2026-09-29 |
| Zhongji Innolight IR (`ir.zj-innolight.com`, `www.zj-innolight.com`) | Not checked | `ir.`: `Disallow: /`; `www.`: `Disallow: /uploads/` (seed-list research, 2026-09-29) | n/a | No | No | **Blocked** (`automation: unchecked`); never fetched: its filings come from HKEXnews |
| FCA National Storage Mechanism (`api.data.fca.org.uk`, `data.fca.org.uk`) | <https://data.fca.org.uk/artefacts/NSM_Terms_of_Use.pdf> (updated 19 Mar 2020) and <https://data.fca.org.uk/artefacts/NSM_General_AUP.pdf> (18 Feb 2020), checked 2026-09-29: "You may use the material and documents contained in the NSM for any lawful purpose not otherwise excluded by these terms and conditions or the Acceptable Use Policy"; uploaders license other users "to use, store and copy that content and to distribute and make it available to third parties including for any lawful commercial purpose"; the AUP forbids reproducing, duplicating, copying or reselling the site and interfering with or disrupting it; the FCA's name and marks may not be used | None (403 on both hosts) | 0.5 requests/s (fixed, live only) | Yes | Yes (English) | **Allowed** (`automation: allowed`): lead, 2026-09-29 (ticket 05) |
| LSE RNS (`www.londonstockexchange.com`, `londonstockexchange.com`, `api.londonstockexchange.com`) | <https://www.londonstockexchange.com/disclaimer>, checked 2026-09-29: RNS is provided "to the general public for personal use"; pages may be stored "on disk (but not on any server or other storage device connected to a network) for personal use" | `User-agent: *` / `Disallow: /en-gb/` | n/a | No | No | **Blocked** (`automation: forbidden`, reason "blocked: LSE disclaimer limits RNS to personal use stored off any network, and robots.txt disallows /en-gb/ (an RNS data licence or written consent required)"): lead, 2026-09-29 |
| IQE's regulatory-news iframe (`polaris.brighterir.com`, Brighter IR) | Not checked | `User-agent: *` / `Disallow: /` (2026-09-29) | n/a | No | No | **Blocked** (`automation: unchecked`); never fetched: IQE's announcements come from the NSM |
| AMF info-financière (`www.info-financiere.gouv.fr`, and the files on `fr.ftp.opendatasoft.com`) | <https://www.data.gouv.fr/dataservices/api-info-financiere>, checked 2026-09-29: licence "Licence Ouverte / Open Licence 2.0" (Etalab: reuse, commercial included, crediting the source and its last update), base URL `https://www.info-financiere.gouv.fr/api/explore/v2.0`, "10000 appels API par ip par jour"; the API answered `X-RateLimit-Limit: 5000` | `www.`: `User-agent: *` … `Disallow: /api/` (Googlebot allowed `/api/`); `fr.ftp.opendatasoft.com`: `Disallow: /` (2026-09-29). Read and recorded with each decision; the register's `api_client` prefixes (the dataset's records and `/datadila/INFOFI/`) are allowed as a documented API's client, anything else on those hosts is blocked | 0.5 requests/s (fixed, live only); ≤ 10 API calls per discovery | Yes | Yes (English only) | **Allowed** (`automation: allowed`, `api_client`): lead, 2026-09-29 (ticket 06) |
| Euronext (`www.euronext.com`, `euronext.com`, `live.euronext.com`, `connect.euronext.com`) | <https://www.euronext.com/en/terms-use> (updated 29 Apr 2021), checked 2026-09-29: "use of any Web browsers (other than generally available third-party browsers), engines, software, spiders, robots, avatars, agents, tools or other devices or mechanisms to navigate, search or determine the Euronext Website is strictly prohibited" without prior written permission; no copying, downloading or compiling "through framing or systematic retrieval to create collections, compilations, databases or directories" | `www.`: only site internals disallowed (2026-09-29) | n/a | No | No | **Blocked** (`automation: forbidden`, reason "blocked: Euronext Terms of Use prohibit robots and systematic retrieval (Euronext's prior written permission required)"): lead, 2026-09-29 |
| Soitec (`www.soitec.com`, `soitec.com`) | <https://www.soitec.com/home/terms-of-use>, checked 2026-09-29 (quoted from its public text via web search): "In no event may you use, distribute, copy, reproduce, modify, distort, or transmit the Web site or any of its elements, such as text, images or sounds without the prior written permission of Soitec" | Not read | n/a | No | No | **Blocked** (`automation: forbidden`, reason "blocked: soitec.com's terms forbid reuse of the site's elements (Soitec's prior written permission required)"): lead, 2026-09-29 |

## 6. Adding a source

1. Add or update the row here with its status, tier, `license_class`, basis and conditions.
2. For `public_issuer` and non-US regulators, add the site to §5.
3. Build the adapter with retry classification, rate limiting, a fixture implementation, metric labels and a kill switch (build plan §12, §13.3).
4. Update [`threat-model.md`](threat-model.md) if the source adds a new path for untrusted content.
