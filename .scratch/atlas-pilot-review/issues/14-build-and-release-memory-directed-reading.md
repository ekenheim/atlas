# Build and release memory-directed reading

Type: task
Status: claimed
Blocked by: none

## Question

Build the spec `.scratch/atlas-memory-directed-reading/spec.md` (eleven tickets in `.scratch/atlas-memory-directed-reading/issues/`), integrate and release it with the `release-atlas` skill, and deploy it.

- Wave 1 (no blockers): 01 Reading pointers, 02 Claim checks, 03 Contradiction or bear context, 04 Specific filing phrases.
- Wave 2: 05 Passage selection (after 01), 08 Layer supported or absent (after 02).
- Wave 3: 06 Multi-hop Investigators (after 01, 05), 07 The Skeptic reads by pointers (after 01, 03, 05).
- Added after the breadth runs: 09 A company-level constraint (after 08), 10 The baseline drops near-duplicates (after 05).
- Added with pilot-review ticket 18: 11 Atlas marks its retains for the MiniMax extractor (no blockers).

Each ticket goes to one implementer agent in its own worktree (`docs/agents/implementer-brief.md`); the lead names the migration revisions, integrates, runs the runners and releases. The answer records the release, the deploy and what each ticket's tests showed.

## Comments

**2026-10-02, the lead: built, integrated and tagged.** All eleven tickets are merged on main at `419d8a1` (runners: 1,402 tests, the frontend gates, the e2e) and tagged `v0.3.0`; details in `docs/implementation-log.md`, "memory-directed reading integrated; release 0.3.0". Open for this ticket: the release run's image, the home-ops PR (image, `ATLAS_RUN_TOKEN_BUDGET` 2,000,000, `ATLAS_RETAIN_EXTRACTOR=minimax`), the owner's merge, and production reporting 0.3.0.

**Handoff, 2026-10-02 (the owner stopped the session for the night; resume here on "continue").**

State when stopped:
- `main` holds the release commit `419d8a1`, tagged `v0.3.0`. The release run 36939346940 was in progress (its `ci` job on the runners, then `publish`). Production still runs 0.2.5.
- The home-ops change for 0.3.0 is committed locally, **not pushed**: checkout `C:\Users\ekenh\home-ops-atlas-pr`, branch `atlas-0.3.0` (image `0.3.0`; `ATLAS_MINIMAX_BUDGET_TOKENS` 8,000,000; `ATLAS_RUN_TOKEN_BUDGET` 2,000,000; `ATLAS_RETAIN_EXTRACTOR=minimax`). Its PR body is drafted in `.scratch/atlas-pilot-review/drafts/home-ops-0.3.0-pr.md`, with the release run's result still to fill in.
- All implementer branches (`worktree-agent-*`) are merged. The remote branches `integrate/mdr-a` to `-d` can be deleted once 0.3.0 is released.
- The lead's helper scripts are in `.scratch/tools/`: `wsl_lead.sh` (run the checks under WSL on this Windows machine: `MSYS_NO_PATHCONV=1 wsl.exe -d Ubuntu -- bash <path> client|static|test ...|frontend`; it has the lead's worktree path in it), `wordmerge.py`, `rechain.py`, `res_mig.py` (integration conflicts), and the breadth-run scripts.

Next steps, in order:
1. Read the release run's result (`gh run view 36939346940`). Success: the image is `ghcr.io/ekenheim/atlas:0.3.0`. Failure: read the job log, fix on `main`, tag `v0.3.1` (a tag is never moved), and change the version in the home-ops branch and the PR draft.
2. In the home-ops checkout: `git fetch`, rebase `atlas-0.3.0` on `origin/main` if it moved, push, open the PR with the drafted body (fill in the release run's result), wait for its checks. The "AI PR Review" check fails on every home-ops PR for a missing input. **The owner merges.**
3. After the merge: production reports `atlas_build_info{version="0.3.0"}` and every readiness check `ok`; `GET /api/v1/queue` lists the `hindsight_minimax` budget; after the first retain, `GET /api/v1/source-versions/{id}/memory` shows `extractor: minimax`. Then resolve this ticket and pilot-review ticket 18.
4. Ticket 15: run investigation 1 on 0.3.0 and review every accepted Claim with the `pilot-review` skill (the baseline script now drops near-duplicates). Then tickets 05 to 08, investigations 2 to 5.
5. The owner's queue is unchanged: 15 edges to decide (ticket 09), 12 gold cases to adjudicate (ticket 10).

**2026-10-02 (morning), the lead: released; the image is live, its settings are not yet.**
- The release run 36939346940 succeeded (`ci` 25m44s on the runners, `publish` 1m33s): `ghcr.io/ekenheim/atlas:0.3.0`.
- Renovate bumped the image in home-ops on its own (PR #7190, merged overnight). Production reports `atlas_build_info{version="0.3.0"}` and every readiness check `ok` (read 07:32 UTC), with the 0.2.5 settings: `minimax` 4,000,000 per window, 1,000,000 per run, no `hindsight_minimax` budget, 104 retains held by the Codex budget.
- The settings went up as home-ops PR #7194 (rebased on #7190, so its diff is `deployment.yaml` only: `ATLAS_MINIMAX_BUDGET_TOKENS` 8,000,000, `ATLAS_RUN_TOKEN_BUDGET` 2,000,000, `ATLAS_RETAIN_EXTRACTOR=minimax`). **The owner merges.**
- The pilot runs do not wait for it: each is started with `budgets.token_budget` 2,000,000 in the request (`.scratch/tools/pilot_runs.py`), which is what #7194 makes the default. What does wait: the `hindsight_minimax` check, `extractor: minimax` on a first retain, and so this ticket and ticket 18.
