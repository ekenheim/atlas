# Map: Atlas pilot, Phases 3–6a

Label: wayfinder:map

## Destination

A ready-for-agent spec (via `/to-spec`) for Phases 3–6a, the rest of the pilot:
- discovery, entity resolution and typed Relationships (Phase 3)
- the controlled research workflow and Hypotheses (Phase 4)
- XBRL financials and scenarios (Phase 5)
- frozen Research Snapshots and the leakage test (Phase 6a)

It ends in the spec §15 demo. The spec will be at `.scratch/atlas-phase3-6a/spec.md`.

## Notes

- **Domain:** as in `.scratch/atlas-pilot/map.md`. Glossary is `CONTEXT.md`; the product spec is authoritative; deviations go in `docs/decisions.md`.
- **Starting point:** Phases 0–2 are built and deployed (Atlas 0.1.1 in `development`, the shared Hindsight bank `atlas-ai-infrastructure`). Method inputs come from ticket 12's adopt list (`.scratch/atlas-pilot/issues/12-serenity-skills-alignment.md`): the Bottleneck test, the layer taxonomy, BOM share, dilution as a falsifier, the bear checklist.
- **Skills:** grilling tickets use `grilling` + `domain-modeling`; research tickets use `research`, written to `docs/research/`.
- **Settled while charting (2026-09-29, owner accepted all):**
  - Destination: Phases 3–6a (6b and 7 are out).
  - Seed list is a draft pending verification (ticket 01): Lumentum, Coherent, Fabrinet, Applied Optoelectronics, Ciena, MACOM, AXT; STMicroelectronics (European, files with the SEC); Soitec or IQE (European, not an SEC filer); Zhongji Innolight (Asian).
  - Non-SEC sources come through a company IR adapter (RSS/press releases, annual-report PDFs), with PDF text extraction added to the deterministic parser. robots.txt and terms are respected, and each source gets a licence class. Non-English filings are archived; extraction is English-only in the pilot.
  - Atlas's own LLM calls (Phase 4 roles) go through LiteLLM with the `atlas` key and MiniMax-M3, budgeted per run and per key. The key is created via a fresh-clone home-ops PR (ticket 02).
  - Entity resolution is deterministic: SEC `company_tickers.json`, GLEIF, OpenFIGI. An LLM only proposes; a person commits.
  - A Relationship is born as a Claim (proposed) → an Assertion (validated span) → reviewed into a typed, directed Relationship (§5.5). A co-mention alone never counts.
  - Discovery uses SearXNG (engines named explicitly, e.g. Bing and Brave). Results are Tier C lead metadata only: they can create a Candidate, never Evidence. There's a query budget per run.
  - Retained into Hindsight: IR press releases and annual reports, bounded and section by section. Never retained: search snippets or news.

## Decisions so far

<!-- one line per closed ticket -->

- [Seed list](issues/01-seed-list.md): 12 companies across 7 layers (Marvell added for DSP); Innolight via HKEXnews (HKEX-listed since 2026-07); most US IR sites block automation, so non-SEC names need HKEXnews/RNS/Euronext-style adapters.

- [XBRL normalization](issues/04-xbrl-normalization.md): as-of by filing availability, never `frame`; tag precedence per concept (revenue tags drift); no segment facts in companyfacts, so product exposure comes from text; restatement plus suspect flag; found the after-hours dissemination bug (→ ticket 10).

- [Entity-resolution sources](issues/03-identity-apis.md): SEC + GLEIF + OpenFIGI in a 4-tier deterministic pipeline; no CIK↔LEI link exists (reviewed once per company); 8 `security` schema gaps; OpenFIGI needs segment MICs.

## Not yet specified

- **Non-SEC source adapters:** HKEXnews (Innolight), LSE RNS (IQE), Euronext/AMF or issuer site (Soitec). Which adapters, feed formats, terms; affects Phase 3 scope. Graduates into a research ticket once 05/06 settle the ingest model.
- **Evaluation gold set** (spec §9.5): 20–30 labelled cases, including the layer-conflation and partner-page traps from ticket 12. Its format is in `docs/evaluation-methodology.md`; which cases, and who labels them, is open.
- **Frontend screens for the pilot** (§10.1 A/B/D/E: Theme explorer, Company dossier, Research workbench, Hypothesis dossier), in what order, and how much UI the demo needs.
- **Mental-model and consolidation cost at scale** on the shared Hindsight (Codex): whether Phase 3's extra sources need the parked dedicated Atlas Hindsight first.
- **Embedding and reranker evaluation** (Qwen3 0.6B vs 4B at 1024 dims; `bge-reranker-v2-m3`), measured on the gold set.

## Parked (owner)

- Centralising Hindsight LLM traffic through LiteLLM; LLM failover; a dedicated Atlas Hindsight. See `.scratch/atlas-pilot/map.md`.

## Out of scope

- Phase 6b (scheduled monitoring and the evidence inbox; the market-data provider decision; paper tracking) and Phase 7 (hardening, restore drill, React Flow map).
- Earnings-call transcripts without a licensed provider (spec §4.2).
