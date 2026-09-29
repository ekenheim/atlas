# Discovery and the Candidate lifecycle

Type: grilling
Status: resolved
Blocked by: none

## Question

Decide:
- how the Scout turns a theme question into SearXNG queries (engines, per-run budget, dedupe)
- what a lead is stored as (Tier C metadata)
- when a lead becomes a Candidate (§8.3 states), and how an unseeded company is proposed, resolved and added to the universe (human commit)
- how discovery results link to primary-source fetching (IR/SEC)

## Answer

Grilled 2026-09-29; the owner accepted all.

- **Scout:** MiniMax turns the theme's research question plus Bottleneck mental-model gaps into ≤10 SearXNG queries per run (engines named: Bing, Brave). Results are deduplicated by canonical URL and stored as Tier C leads (URL, title, snippet, query, engine, date), never Evidence.
- **Lead → Candidate:** a lead naming an unseeded company proposes a Candidate (`lead`) after deterministic entity resolution (ticket 03). **The owner commits** it into the universe, which triggers SEC/exchange ingest. Candidates are never deleted, including rejected ones.
