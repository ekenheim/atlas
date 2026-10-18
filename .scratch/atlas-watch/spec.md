# Spec: Chokepoint Watch, Atlas as a discovery engine

Status: ready-for-agent (W1, W3, W4); W2 and W6 follow W1. Opened 2026-10-18 by the lead, at the owner's request, after three outside reviews.

## Why

The owner's goal is to find where demand will outrun qualified supply, who holds the scarce input, and whether they capture the economics, before the market prices it. Atlas has become good at proving a thesis it was pointed at (InP: 20 proven Beliefs, one published Hypothesis, four dated predictions). It has never had to find one.
- The universe is a config list the owner and the lead picked.
- The scorecard's closed-book arm showed the model already knows the famous cases.
- Three outside reviews (2026-10-18) agree: separate cheap prospective discovery, where leads may be unverified, from Atlas's proof, which stays as strict as it is. Run discovery weekly, as deltas, from an industry definition rather than a ticker list.

## What already exists, and is reused (no rebuild)

| The reviews ask for | Atlas has |
|---|---|
| Tier L leads (rank, never support) | `lead` rows: Tier C, never Evidence (SearXNG, EDGAR FTS, TradingView news, archive signals) |
| Tier P evidence (dated, quoted) | Facts: verbatim spans of archived Source Versions, as-of bound |
| An untrusted search map from the model's priors | Issues (`question`, `narrows`, `requires`): never evidence |
| Thesis-ready → proven | `propose_belief`, the judge, `POST /hypotheses`, the publish gate |
| Predictions settled against what followed | the prospective record (ticket 19): calls, checkpoints, predictions |
| Keep the losers, append-only | Candidates, Issues, Beliefs (superseded, never deleted), the audit chain |
| Weekly deltas | `newest_documents(since)`, `signal_leads(since)`, the nightly ingest and signal scan |
| Infrastructure kept out of the agents' prompts | the agent prompts are already short; the infrastructure text lives in AGENTS.md, which agents never read |

**Not accepted:** the claim (one review) that the verbatim-span rule stalls discovery. Issues were always untrusted. What stalls it is that nothing ever asks the model to decompose an industry and look outside the universe.

## What is missing (the tickets)

**W1: the board.** A `chokepoint` record per candidate bottleneck:
- **fields:** constraint, layer, holders (companies, possibly outside the universe, by name, with CIK if known), status, the six bottleneck-test steps, kill criteria (observables), relief horizon with its basis, crowding (`early`, `emerging` or `consensus`; context, never evidence), a theme and the run that created it;
- **status:** `lead` → `candidate` → `thesis_ready`, or `stale` (no evidence for 8 weeks) or `killed` (with a reason);
- **each step's status:** `unexamined`, `lead`, `primary` or `contradicted`, set with the Fact (`primary`, `contradicted`) or the lead or Issue (`lead`) that justifies it; a `primary` step needs a Fact.

Every change is an insert-only `chokepoint_event` row (what changed, why, the evidence, the session). The read side folds the events into the current state. Nothing is deleted: a killed chokepoint stays listed.
- **Routes:** `GET/POST /api/v1/chokepoints`, `GET /chokepoints/{id}` (state and history), `POST /chokepoints/{id}/events`.
- **MCP tools:** `board`, `get_chokepoint`, `add_chokepoint`, `update_chokepoint`. Every one refuses an isolated session (`refuse_isolated`), and all are additive to ticket 29's frozen surface.
- **The run record:** a `watch_run` row (theme, run date, mode `architect` or `delta`, the memo's markdown, counts, tool calls, cost), via `POST /api/v1/watch-runs` and MCP `write_memo`.
- **Owner pages:** the Today page shows the latest memo, and the theme page leads with the board. The routes are built here; the frontend tab builds the pages.
- Thesis-ready means steps a, b and d are `primary`, at least one kill criterion is written and at least one Issue is open. It is the hand-off to a Researcher session and Beliefs.

**W2: the Watch agent.** `agent/prompts/watch.md`, `run.sh watch`, a weekly CronJob per theme.
- **The lens:** the six-step test, separate checks of physical scarcity, economic capture and investability, the bear kill-switch, the signal catalogue of tightness and relief, and the anti-patterns. It is ticker-free and names no case of the scorecard or of the Serenity skill.
- **The procedure:**
  1. Load the board and the last memo.
  2. Settle predictions that are due.
  3. Sweep for deltas since the last run, across every layer.
  4. Update the board.
  5. Discover at most 3 new candidates; every hop needs at least a lead.
  6. Deep-dive at most 2, disconfirming evidence first.
  7. Predict.
  8. Write the memo.
- **Stop rules and budgets:** at most 60 tool calls, and "a quiet week is a valid result".
- **Week 1 (`architect` mode):** decompose the industry from its demand driver down to feedstock and gating equipment, as Issues labelled "from the model's priors, untrusted", with no seed company, and sweep 90 days instead of 7.
- **After the board is committed:** a Serenity diff of the theme (independent, convergent, his only, divergent). It reads two reference files and changes nothing on the board; seeding from it is off.
- **Scheduling:** the CronJob fires on a day no other judge-using agent fires (Saturday), because the scorecard, the DRAM Researcher and the Watch share the judge's 5-hour window.

**W3: primary sources beyond filings (phase 1 by 1 November).**
- **Company pages:** a company's own investor-relations and press pages, decks and slides, fetched through the fetch gate (site register, terms, robots.txt) into the archive as Source Versions. Atlas can then quote them as Facts. One adapter, `sources fetch --url`, for a site the register allows. The gate exists; the adapter is new.
- **EDGAR full-text search as an MCP tool** (`filing_search`: a phrase, forms and a window, every filer, results as leads).
- **SearXNG web search as an MCP tool** (`web_search`), results stored as leads with their publication date.
- **Phase 2 (later):** EDINET/TDnet, MOPS and DART need API keys (the owner's act), and government notices.

**W4: mechanical bear checks.** `GET /api/v1/companies/{id}/bear-checks?as_of=`, deterministic and with no LLM call:
- dilution: shares-outstanding growth from XBRL, and S-3, S-1, 424B5 or F-3 filings in the last 12 months (an ATM shelf);
- GAAP gross margin, trailing four quarters, from XBRL;
- customer concentration ("accounted for N% of revenue" in the latest 10-K or 20-F text);
- going-concern language;
- net cash or debt.

Each check has its source span or observation. MCP `bear_checks`. The Skeptic and the Watch read it.

**W5: is it discovering anything?** Measures, reported monthly; no target before the first run:
- **Scan precision@20:** blind readers class the top 20 filers as holder, squeezed or noise.
- **First named:** the date each company and chokepoint first entered the board, against the date it was admitted to the universe. Compared with prices only after a year.
- **Redundancy:** the same constraint and layer created twice.
- **Cost per thesis-ready chokepoint:** tool calls and tokens.
- **Settlement:** predictions and calls settled, hit or miss.
- **Kill rate:** killed chokepoints, with their reasons.

**W6: one greenfield industry: robotics manufacturing** (the owner's choice, 2026-10-18). An industry Atlas has never touched. Its key suppliers are often Japanese, so they stay leads until phase 2's registries are in. Its theme config needs an empty company list, which is a config change if the loader requires companies. Started by the architect run with zero seed companies. Holders are admitted to the universe as they become candidates: a Candidate committed, SEC ingest and the TradingView catalog. Four weekly cycles, then the owner judges the output, not the code.

**W7: ticket 33's scan feeds the Watch.** The EDGAR phrase scan runs weekly as a delta, and its shortlist arrives as leads. Ticket 33 closes into this effort.

## Explicitly not built, and why

- **A rewrite.** Everything above is additive.
- **A separate state store** (one review suggested a git repository). Atlas has the database, the audit chain and the owner's pages.
- **New Hindsight work.** Its measured contribution is small and bulk retention is off. The conclusions bank stays as it is.
- **Discovery on the MiniMax role pipeline.** The sessions beat it at a tenth of the tokens.
- **Installing the Serenity skill.** Its two reference files are read only for the post-commit diff.
- **More scorecard investment.** It runs as built and pre-registered, but the closed-book arm already said it won't discriminate. The prospective record is the test.

## Constraints carried

- **Ticket 29's frozen surface.** Every new MCP tool refuses an isolated session. A test asserts that the isolated researcher's `--dry-run` prompt and command are byte-identical to v0.6.14's. The scorecard cases stay off the board and out of every new theme until ticket 29's runs are done.
- **Prices** are never evidence, and the board records crowding as context only.
- **The Watch is prospective.** It runs as of its run date and is never used for backtests.

## Done by 1 November 2026

- One greenfield theme exists, started from its industry definition with no seed company.
- The architect decomposition is on the board as Issues, with one 90-day sweep.
- A memo is on the Today page: discoveries, rejections, changes, next questions.
- At least one chokepoint carries kill criteria and a dated prediction.
- No Fact exists outside an archived span.
- The second weekly run is scheduled.

Fewer, evidenced lines beat a full board.
