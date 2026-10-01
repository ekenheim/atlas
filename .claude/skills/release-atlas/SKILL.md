---
name: release-atlas
description: Integrate finished ticket branches, release an Atlas version and deploy it to the owner's cluster. Use when merging agent branches to main, cutting or retrying a release tag, opening the home-ops image-bump PR, or confirming a deploy is live.
---

# Release Atlas

The path from finished branches to a live version. Each step's completion criterion is a green check you can point at; `docs/deployment.md` is the authority where this is silent.

## 1. Integrate

1. In the integration worktree (`/mnt/c/Users/ekenh/atlas-integrate`), branch from `main` and `git merge --no-ff` each ticket branch, oldest base first. Conflicts to expect: `AGENTS.md` (two edits to one long line: keep both), `docs/implementation-log.md` and `docs/decisions.md` (keep both entries), `tests/integration/test_migrations.py` (the head).
2. **Chain the migrations:** every branch based its migration on main's head; re-point each `down_revision` (and the docstring's `Revises:`) so the chain is linear, and set the head the migration test expects.
3. Regenerate the API client (`scripts/gen_api_client.sh`, or `export_openapi.py` plus `openapi-typescript` from a checkout that has `node_modules`) and commit the result; CI fails on a stale client.
4. Expect **semantic conflicts** between fixes that each passed alone: a test one fix added that the other fix's behaviour changes (a new Editor call, a parse length). Run only the modules the merge touched locally; the runners run the suite.
5. Run `ruff format --check`, `ruff check` and `pyright` locally, then push the branch as `integrate/<name>` from the main checkout with Windows `git.exe -c safe.directory='*' push origin <sha>:refs/heads/integrate/<name>` (WSL git has no credentials; `git.exe` reads stdin, so give it `</dev/null` inside scripts). Poll the run through the GitHub API with the token from `git.exe credential fill` (never print it). A failure: read the job log, fix on the integration branch, push again.

On the owner's Windows PC the integration can be done in a Windows worktree: run the checks under WSL with `.scratch/tools/wsl_lead.sh` (native pytest fails in the harness's CLI subprocess), merge two edits to one long `AGENTS.md` line with `.scratch/tools/wordmerge.py`, and re-chain with `.scratch/tools/rechain.py` and `res_mig.py`. Windows `git` and `gh` push with the owner's credentials. Two tests that compare a prompt file byte for byte fail only in a CRLF checkout.

Completion: the integration branch's `ci` run is `success`.

## 2. Release

1. `git merge --ff-only` the integration branch into `main`, push `main`, then delete the merged remote work branches after `git merge-base --is-ancestor` confirms each is in `main`.
2. Tag the next patch version (`git tag -a vX.Y.Z -m ...`) on the green commit and push the tag. **A tag is never moved or re-pushed**: a failed release means a fix on `main` and the next patch number (0.2.2 was cancelled by a runner limit and shipped as 0.2.3).
3. Wait for the `release vX.Y.Z` run: its `ci` job runs on the self-hosted scale set, its `publish` job on GitHub's runners. Completion: `publish` is `success`; the image is `ghcr.io/ekenheim/atlas:X.Y.Z`.
4. Log the integration and release in `docs/implementation-log.md`.

## 3. Deploy

1. In `/mnt/c/Users/ekenh/home-ops-atlas-pr`: `git.exe fetch`, `git checkout -B atlas-X.Y.Z origin/main`, bump the image tag in `kubernetes/apps/development/atlas/app/{deployment,ingest}.yaml`, and check whether the release needs a new env var or secret (a setting with a default and a config that ships in the image need nothing). Rename the branch if the version changed since it was created.
2. Commit, push with `git.exe`, open the PR through the API. The body carries **provenance**, which the repo's AI reviewer requires: tag and commit, the release run URL, the CI run URL, the migrations (revision, what each adds, that none is destructive), and why this version number. Then wait for the check runs on the branch's head commit.
3. **The owner merges.** Report the PR link and the check results; don't merge.
4. After the merge, poll `/metrics` for `atlas_build_info{version="X.Y.Z"}` and `/health/ready` for every check `ok`; read `/queue` for the budgets. Log the deploy.

Completion: production reports the version and is ready.
