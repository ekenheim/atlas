# Atlas Research: agent guide

Evidence-driven investment research platform built around Hindsight. Start with `START_HERE.md`; the authoritative spec is `hindsight_investment_research_build_plan.md` (v1.1).

## Commands

- `scripts/ci.sh`: the one CI entrypoint (GitHub Actions runs exactly this). `--no-image` skips the image build.
- `uv run pytest`: unit tests (network blocked by pytest-socket) and integration tests (localhost only; needs `docker compose up -d --wait postgres-app silo`).
- `uv run atlas api | worker [--once] | migrate`: the three roles of the one image.
- `npm --prefix frontend run lint | typecheck | build`: the frontend gates; `build` writes the static export to `frontend/out/`.

## Layout

- `backend/atlas/`: the Python package (`api/` FastAPI app, `db/` migrations, `settings.py`, `health.py`, `cli.py`)
- `frontend/`: Next.js static export, served by FastAPI
- `tests/unit`, `tests/integration`: tests at the agreed seams (HTTP API, CLI entry, migrations)
- `configs/`: versioned config (e.g. Hindsight bank templates)
- `spikes/hindsight/`: the Hindsight 0.10.1 spike, fixtures and recordings (contract-test source)
- `.scratch/`: the local issue tracker (the decision map and build tickets)

## Conventions

- Test-first at agreed seams only; test behavior through public interfaces, never internals. Real Postgres, never SQLite.
- Settings are `ATLAS_*` env vars (or `.env`), validated at startup. Optional providers log `<provider> disabled: missing <VAR>` once.
- Ruff and strict pyright must be clean; TypeScript is strict.
- Record each ticket's files, tests and results in `docs/implementation-log.md`. Never claim a live integration was tested when only fixtures were.

## Agent skills

### Issue tracker

Local markdown files under `.scratch/` (no remote tracker). See `docs/agents/issue-tracker.md`.

### Triage labels

Default five-role vocabulary (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Hindsight skills

- `hindsight-docs` is the Hindsight 0.10.1 documentation and OpenAPI schema, pinned to the server version. The feature matrix and recordings win where they disagree.
- `hindsight-self-hosted` gives development memory in the **`atlas-dev`** bank on the owner's shared Hindsight, via the `hindsight` CLI. Never use Atlas's research banks for it, and keep decisions in the repo.

### Domain docs

Single-context: `CONTEXT.md` + `docs/adr/` at the repo root. See `docs/agents/domain.md`.
