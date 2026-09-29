# Atlas Research

Evidence-driven investment research on [Hindsight](https://github.com/vectorize-io/hindsight): discover industry bottlenecks, map exposed companies through source-backed evidence, and freeze falsifiable hypotheses for later evaluation. It researches; it never trades.

- **Spec:** `.scratch/atlas-pilot/spec.md` (Phases 0–2), with build tickets in `.scratch/atlas-pilot-build/issues/`
- **Product spec:** `hindsight_investment_research_build_plan.md` (v1.1); deviations in `docs/decisions.md`
- **Glossary:** `CONTEXT.md`

## Quick start (fixture-only, no keys)

```bash
cp .env.example .env
docker compose up -d --build --wait api   # postgres + silo (S3) + migrate + api
curl http://127.0.0.1:58080/health/ready  # database/archive ok, hindsight/litellm not_configured
open http://127.0.0.1:58080/              # static frontend served by the API
docker compose up worker                  # worker checks in and exits (queue: ticket 04)
```

## Development

```bash
uv sync                                    # Python 3.12 env from uv.lock
docker compose up -d --wait postgres-app silo
uv run atlas migrate                       # schema to head (uses .env)
uv run pytest                              # unit (network blocked) + integration (localhost only)
scripts/ci.sh --no-image                   # the CI entrypoint, without the image build
scripts/ci.sh                              # full CI: gates, tests, image build + smoke
```

The app is one image with three roles: `atlas api`, `atlas worker [--once]` and `atlas migrate`.

Local Hindsight 0.10.1 (pinned digest, configured like the spike) is behind a Compose profile, so the default stack needs no LLM. It sends all LLM, embedding and rerank traffic to LiteLLM:

```bash
docker compose --profile hindsight up -d --wait hindsight   # needs ATLAS_LITELLM_URL / _API_KEY
ATLAS_HINDSIGHT_URL=http://127.0.0.1:58888 uv run atlas hindsight apply-template
```

The live Phase 2 gate suite runs against that stack with MiniMax via LiteLLM. It is opt-in, never runs in CI, and **spends MiniMax quota**; see `docs/runbooks.md`, "Live test suite":

```bash
scripts/live-tests.sh --rehearse                   # the same scenarios against the recorded fakes (free)
scripts/live-tests.sh --model MiniMax-M3 --down    # live: brings up Hindsight, runs, records, tears down
```

## Releases

Push a tag `vX.Y.Z` to publish `ghcr.io/ekenheim/atlas:X.Y.Z` (amd64). The release workflow runs `scripts/ci.sh --no-image` first and smokes the image before pushing it. After the very first release, set the GHCR package to **Public** once in GitHub's package settings; new packages start private. See `docs/deployment.md`.
