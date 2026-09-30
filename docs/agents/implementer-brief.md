# Implementer brief: Atlas build tickets

The lead points each implementer agent at this file and at one ticket. Read it fully before starting.

You implement exactly ONE build ticket in your own git worktree/branch of the Atlas repo. Other agents implement sibling tickets in parallel; the lead merges branches into `main`.

## Read first (context pointers)
- Your ticket: the file under `.scratch/` named in your prompt (`docs/agents/issue-tracker.md` describes the tracker)
- Spec: `.scratch/atlas-phase3-6a/spec.md`, and the decision map `.scratch/atlas-phase3-6a/map.md` with its resolved tickets `.scratch/atlas-phase3-6a/issues/` (the Answers are binding). Earlier phases: `.scratch/atlas-pilot/spec.md`. Product spec: `hindsight_investment_research_build_plan.md` (sections cited as §N)
- Research notes live on branches `research/seed-list`, `research/identity-apis`, `research/xbrl-normalization` (read with `git show <branch>:<path>`; `git ls-tree -r --name-only <branch>` lists them)
- `AGENTS.md` (commands, layout, conventions), `CONTEXT.md` (glossary: use its terms in names), `docs/decisions.md`, `docs/adr/`
- `docs/implementation-log.md` (the ticket-01 entry shows the expected format)
- Existing code in `backend/atlas/` and `tests/`, which established the conventions

## How to work
- **Test-first (red → green) at the spec's agreed seams only:** the HTTP API (FastAPI TestClient), the `atlas` CLI entry, the worker single pass, and adapters at the transport boundary. Test behavior through public interfaces, never internals. Integration tests use the real Postgres; never SQLite. Expected values come from the spec or fixtures, never recomputed the way the code does.
- **Tests:**
  - Unit tests: `tests/unit/`, network blocked.
  - Integration tests: `tests/integration/`, localhost only. Use the `empty_database_url` fixture in `tests/integration/conftest.py` for a fresh DB (run `atlas migrate` or `atlas.db.migrate.upgrade` on it).
- **Shared services are already running.** Postgres is at `127.0.0.1:55432` (atlas/atlas/atlas) and Silo (S3) at `127.0.0.1:59000` (root `atlas-dev` / `atlas-dev-secret`). **Do not** run `docker compose down/up/restart` or change those services. Don't bind host ports 55432, 59000, 58000 or 58080.
- **CI runs on the owner's self-hosted runners, not locally.** Run only fast local checks yourself: `uv run ruff format --check . && uv run ruff check . && uv run pyright`, the frontend gates if you touched `frontend/`, and the specific test modules you changed (`uv run pytest tests/<module>.py`). For the full suite, **commit and report**: worktree isolation stops you pushing, so the lead pushes your branch as `ticket/<NN>-<slug>` and runs it on the runners (~8–10 min). If it fails, the lead sends you the log; fix, commit, and report again. Don't run the full `scripts/ci.sh` locally.
- **Dependencies:** add them with `uv add` (runtime) or `uv add --dev`, keeping `uv.lock` consistent. Keep runtime deps minimal and justified.
- **Migrations:** your worktree is on a fresh branch from `main`; don't reset it. If you need a migration, use the revision your prompt names, with the `down_revision` it names (main's head at the time); the lead re-chains migrations at integration.
- **User-Agent:** non-SEC HTTP sources use `settings.exchange_user_agent` (generic, never personal data); only SEC requests carry a contact email.
- **Do not kill other processes:** never `pkill`/`killall` pytest or anything else; other agents run CI concurrently on this machine. Stop only processes you started, by PID.
- **Test theme configs:** every company in a theme config needs `source_path` (`sec` needs a CIK); see `configs/themes/ai-infrastructure.yaml` and `atlas.companies`.
- **Pausable job kinds:** if you register a new pausable kind, add it to `PAUSABLE_KINDS` in `tests/integration/test_queue_pause.py`.
- **No live calls:** no LLM, SearXNG, SEC, GLEIF, OpenFIGI or exchange requests in tests; record or hand-write fixtures under `tests/fixtures/` and fake at the transport. If you need a real response shape, cite its documentation in the log rather than calling the service.
- **API client:** if you add or change API routes, run `scripts/gen_api_client.sh` and commit `frontend/lib/api/`. CI checks it's current.
- **Local Playwright:** don't run the e2e locally; the runners run it. (If you must, on the Ubuntu 20.04 WSL box it needs `PLAYWRIGHT_HOST_PLATFORM_OVERRIDE=ubuntu22.04-x64`.)
- **Scope:** stay inside your ticket. If you must touch a shared file (`settings.py`, `api/app.py`, `cli.py`, `compose.yaml`, `pyproject.toml`), make small additive edits so merges stay easy. Don't refactor code outside your ticket.
- **Secrets:** never commit credentials or keys. `.env` is not in your worktree; tests must not need it.

## When done
1. Tick your ticket's acceptance boxes that are truly met, and set `**Status:** done`. If something isn't met, leave it unticked and explain why in the log.
2. Append an entry to `docs/implementation-log.md` in the ticket-01 format:
   - files
   - tests run with their **actual** results
   - what was only fixture-tested vs live
   - deviations
   - next
3. Commit on your branch, ending the message with the attribution line your prompt gives.
   **Never push, never touch `main`.**
4. Reply with ≤200 words:
   - your branch name and final commit
   - what was built
   - the test count and the local checks you ran (the lead reports the runner CI result)
   - shared files you touched
   - any deviation or open issue

