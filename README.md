# Atlas Research

Atlas is a private research platform for finding **bottlenecks** in an industry's supply chain: inputs, process steps or capacity whose qualified supply may fall short of demand. It maps which companies are exposed to them, and it builds each conclusion from evidence you can check. It researches and never trades.

It is built around [Hindsight](https://github.com/vectorize-io/hindsight) as long-term memory. Postgres is the system of record, and every conclusion traces back to an exact quote in an archived primary source. The first theme is **photonics for AI data centers**: 12 companies from substrate to system (AXT, Soitec, IQE, Coherent, Lumentum, MACOM, STMicroelectronics, Marvell, Zhongji Innolight, Applied Optoelectronics, Fabrinet, Ciena).

## What it does

```
sources ──► ledger & archive ──► triage ──► Hindsight memory
   │                                              │
   └──► Claims ──► Assertions ──► Relationships ──┤
                                                  ▼
 investigation: Scout → Investigators → Skeptic ∥ Financial Analyst → Editor
                                                  │
                          Hypothesis ──► scenarios ──► publish ──► Research Snapshot
```

- **Sources.** Atlas fetches only through sources whose terms it has checked:
  - SEC EDGAR: US filers and XBRL financials.
  - FCA National Storage Mechanism: UK issuers such as IQE.
  - AMF info-financière: French issuers such as Soitec.
  - Manual import of documents you download yourself, for example from HKEXnews for Innolight, whose terms forbid automation.
  - Optionally, TradingView transcripts and news leads. This is an owner override and off by default.

  Every fetch passes a gate built from a site register, the site's terms and its robots.txt.
- **Ledger and archive.** Every document version is stored content-addressed, with its provenance and the time it became public (`available_at`). The audit trail is hash-chained.
- **Retention triage.** A cheap model reads each new document section by section. Only sections with durable, bottleneck-relevant content go into Hindsight: in live runs, 17 of 80 sections. Everything else stays archived and citable.
- **Claims → Assertions → Relationships.** The Investigator proposes Claims. A Claim becomes an Assertion only as an exact quote span in the archived text, and only with an allowed relationship type in an explicit direction. A Reviewer model and deterministic checks turn Assertions into typed, directed supply-chain edges (layer-tagged when the quote names a layer), and send anything uncertain to your exceptions queue. Syndicated copies of one announcement count as a single Evidence Family.
- **Discovery.** The Scout searches the web through SearXNG. Results are Tier C leads, never evidence. Companies named in leads that aren't in the universe become Candidates, which you commit or reject.
- **Investigations.** A fixed, budgeted plan: Scout → one Investigator per company → an independent Skeptic, working from a bear checklist ∥ a Financial Analyst → an Editor. Each investigation stops with a recorded reason and can be resumed.
- **Hypotheses.** A draft holds the thesis, mechanism, predictions, catalysts, falsifiers, unresolved questions and alternatives, with citations. Versions are immutable once published, and you can diff them and export them as JSON or Markdown.
- **Scenarios.** Deterministic low, base and high cases, including bill-of-materials share, built on as-of XBRL financials. Every input is sourced or estimated with a stated basis, and there is a ±20% sensitivity table. Identical inputs give identical bytes.
- **Publish and snapshot.** Publishing requires a falsifier, an unresolved question and your approval of every Relationship the version depends on. It freezes an insert-only Research Snapshot, whose hash is verified on every read. A later contradicting source proposes an update and never changes the snapshot.
- **Time integrity.** Nothing is used before it was public. Replay banks rebuild memory as of a cutoff date to prove future sources never leak into a past view.
- **Pacing.** LLM work runs in rolling 5-hour budgets per subscription: Codex for Hindsight and MiniMax for Atlas's own roles. Your interactive work takes priority over backfill.

## Pages

The web UI is a Next.js static export served by the API. It has:
- the source viewer, where you create Assertions from a selection and see highlighted spans;
- the theme explorer and company dossier;
- the Relationship table and exceptions queue;
- the research workbench;
- the Hypothesis dossier, with diff, scenarios, the publish gate and the snapshot.

`/docs` serves the full OpenAPI description of the HTTP API.

## Status

- **Built:** Phases 0–6a. **Deployed:** 0.2.0 in the home cluster's `development` namespace (`kubernetes/apps/development/atlas` in home-ops).
- **Verified live** (2026-09-30) against the real services: SEC, the FCA NSM, the AMF, SearXNG, GLEIF, OpenFIGI, MiniMax and a throwaway Hindsight bank. The results are in `docs/implementation-log.md`.
- **Out of scope for now:** scheduled monitoring and market data (6b), and hardening and a restore drill (7).

## Documents

- `START_HERE.md`: the handoff and orientation.
- `hindsight_investment_research_build_plan.md`: the product spec (v1.1).
- `CONTEXT.md`: the glossary. `docs/decisions.md`: every decision and deviation, including the source terms checks. `docs/adr/`: the architecture decision records.
- `.scratch/`: the local issue tracker (decision maps, specs and build tickets per phase).
- `docs/runbooks.md`: operations (rollout, budgets, live tests, TradingView, replay). `docs/data-model.md`: the database schema. `docs/implementation-log.md`: what was built, tested and verified.
- `AGENTS.md`: commands and layout, for coding agents.

## Quick start (fixtures only, no keys)

```bash
cp .env.example .env
docker compose up -d --build --wait api   # postgres + silo (S3) + migrate + api
curl http://127.0.0.1:58080/health/ready  # database/archive ok, hindsight/litellm not_configured
open http://127.0.0.1:58080/              # the web UI, served by the API
```

## Development

```bash
uv sync                                    # Python 3.12 env from uv.lock
docker compose up -d --wait postgres-app silo
uv run atlas migrate                       # schema to head (uses .env)
uv run pytest                              # unit (network blocked) + integration (localhost only)
scripts/ci.sh --no-image                   # the CI entrypoint, without the image build
```

The app is one image with three roles: `atlas api`, `atlas worker [--once]` and `atlas migrate`. CI (`scripts/ci.sh`) runs on every push, on the owner's self-hosted runner scale set.

A local Hindsight 0.10.1 runs behind a Compose profile and sends all model traffic to LiteLLM:

```bash
docker compose --profile hindsight up -d --wait hindsight   # needs ATLAS_LITELLM_URL / _API_KEY
```

## Live verification

These scripts are opt-in and never run in CI. They spend real quota and need `.env` (LiteLLM, Hindsight):

```bash
scripts/live-verify.sh --rehearse          # every part against the fakes (free)
scripts/live-verify.sh --yes               # live: SEC→triage→Hindsight, exchanges, discovery,
                                           # Relationships, an investigation to a published snapshot,
                                           # identity; capped at 40 model calls and 25 retains
```

## Releases

Push a tag `vX.Y.Z` to publish `ghcr.io/ekenheim/atlas:X.Y.Z`. Deploy by bumping the image in home-ops (`docs/deployment.md`).
