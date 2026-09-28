# Implementation log

Per `START_HERE.md`: after each ticket or phase, record the files, the acceptance tests run and their **actual** results, open blockers, credential dependencies, version decisions and the next task. Say plainly when something was only tested against fixtures.

## 2026-09-28: ticket 01, walking skeleton

- **Built:**
  - uv project (Python 3.12.10, `uv.lock`)
  - `atlas` package: FastAPI app factory, settings, health, JSON logging, CLI `api | worker [--once] | migrate`, Alembic baseline revision `0001`
  - Next.js 16.3 static export (TypeScript 6.0 strict, ESLint 9)
  - multi-stage Dockerfile (non-root uid 10001, read-only-root compatible)
  - Compose: `postgres-app` (Postgres 17), `silo` (PGSTY Silo, pinned digest), `migrate`, `api`, `worker`
  - `scripts/ci.sh`, `scripts/image-smoke.sh`, `.github/workflows/ci.yml`
  - `.env.example`, README, AGENTS.md
- **Tests (TDD at the agreed seams):** 11 passing:
  - liveness
  - readiness: ok, database down, archive down (all fail closed with 503)
  - metrics
  - static frontend mount
  - CLI: missing required settings fail fast, `worker --once` with disabled-provider notices
  - settings: CRLF `.env` and CR-in-env stripping
  - migrations from an empty database

  A mutation check confirmed the fail-closed tests go red when readiness always reports ready.
- **CI entrypoint:** `scripts/ci.sh` passed locally end to end (≈3.5 min). **GitHub Actions has not run yet**: the workflow is committed but unverified on a runner.
- **Manual check:** `docker compose up -d --build --wait api`, then `/health/ready` reported database and archive `ok` and Hindsight/LiteLLM `not_configured`; `/` served the frontend; `/metrics` exposed `atlas_build_info`; logs are JSON.
- **Deviations and notes:**
  - The dev dependency is `httpx2`, because Starlette deprecates `httpx` for its test client.
  - The API host port defaults to 58080 (8000 was taken locally), configurable via `ATLAS_API_PORT`.
  - The Compose worker runs `--once` until the job queue exists (ticket 04).
  - The S3 archive backend is not wired into readiness yet; that's ticket 05.
- **Credentials:** none needed.
- **Next:** tickets 03 (audit trail), 04 (job queue), 05 (archive), 06 (EDGAR adapter), 11 (Hindsight gateway) and 18 (release pipeline) are unblocked. Ticket 02 (docs pack) and 20 (home-ops prerequisites) were unblocked already.

## 2026-09-28: ticket 20, home-ops prerequisites (PRs 1–3)

- **Built:** three local branches in home-ops (`/mnt/c/Users/ekenh/home-ops-upgrade`), each in its own worktree under the session scratchpad, all off `main` @ `c1531a6b0`. Not pushed. The canonical checkout's `main` working tree was not touched.
  - `atlas/crunchy-users` @ `29dfa1c19`: PGO users/databases `atlas` and `atlas-hindsight` in `database/crunchy-postgres/cluster/cluster.yaml`, with a comment pointing at the `vector` runbook.
  - `atlas/litellm` (**changes staged, not committed**; see Deviations):
    - configmap: aliases `atlas-extract` / `atlas-reflect`, both `<<: *minimax-m3`. The anchor is new, on the existing `MiniMax-M3` route's `litellm_params`. Each alias has its own `model_info`, because the configmap forbids anchored `model_info`.
    - configmap: the PRIVACY note amended with the Atlas exception for public-market research.
    - `keys/atlas.yaml`: `LiteLLMVirtualKey` `atlas` → Secret `litellm-key-atlas` (`api-key`); `maxBudget: "25"`, `budgetDuration: 30d`, `maxParallelRequests: 3`; models `atlas-extract`, `atlas-reflect`, `qwen3-embedding-0.6b`, `rerank`.
    - `clustersecretstore/` plus a Flux Kustomization `litellm-stores` (dependsOn `external-secrets`): ClusterSecretStore `litellm-key-secrets` with `remoteNamespace: llm` and `conditions: [{namespaces: [datasci]}]`; SA `external-secrets-llm` with a namespaced Role/RoleBinding in `llm` allowing only `get` on `litellm-key-atlas`.
  - `atlas/renovate` @ `1b2ab3564`: two rules appended last in `.github/renovate/packageRules.json5`, both `automerge: false`: `matchFileNames: kubernetes/apps/datasci/atlas/**` (covers the dedicated Hindsight, whose package names it shares with `llm/hindsight`) and `matchPackageNames: ghcr.io/ekenheim/atlas`.
  - Atlas repo: `docs/runbooks.md` covers the home-ops PR merge order (with per-step checks and the names later releases depend on) and the one-off `CREATE EXTENSION vector` in `atlas-hindsight`.
- **Validation (actual results):**
  - **yamllint:** `yamllint -c .yamllint.yaml -s .` passed on all three worktrees. This mirrors home-ops CI, whose config ignores `.github/`.
  - **kubeconform v0.6.7:** `-strict`, default k8s schemas, run on the 6 changed manifests (10 resources): Valid 10, Invalid 0, Skipped 0.
    - CRD schemas were generated from the **pinned** CRDs, not the datree catalog CI uses, because the sandbox refused that URL: litellm-operator 0.0.19, external-secrets 2.11.0, pgo 6.0.3, and Flux Kustomization from flux CLI v2.0.0-rc.1.
    - A negative check (a misspelled `maxParallelRequest`, `conditions[].namespace`) was rejected, which confirms the schemas are strict.
  - **flux-local v8.4.0** (the CI image), `test --all-namespaces --path kubernetes/flux/config`:
    - crunchy-users 182 passed, renovate 182 passed, litellm 183 passed (+1, the new `litellm-stores` Kustomization).
    - With `--enable-helm`, as CI runs it: litellm 325 passed. It was not re-run with helm on the other two, which change no HelmRelease.
  - **renovate-config-validator** (renovate 44.117.0 via npx, node 22.0 under the required engine): "Config validated successfully".
    - Its only warning is a config migration for the existing terraform rule's `matchPackagePatterns`, which predates this change.
  - `${…}`: none of the changes contain a literal `${`, so nothing needed escaping. No ExternalSecrets were added in these PRs, so the `{{ index . "X" }}` rule doesn't apply yet. No secrets.
  - **CRD check:** `maxParallelRequests` (int64) is in the 0.0.19 `LiteLLMVirtualKey` CRD, and the controller sends it as `max_parallel_requests` (checked in upstream source at tag 0.0.19). So the cap is included.
  - **Atlas `scripts/ci.sh --no-image`:** passed, 11 tests (docs-only change here).
- **Fixture vs live:** nothing was applied to the cluster. No kubectl, no LiteLLM calls. The alias resolution was checked by parsing the rendered `config.yaml`: both aliases' `litellm_params` equal MiniMax-M3's.
- **Deviations and open issues:**
  - **`atlas/litellm` is not committed.** 33 of the 256 loose-object dirs in home-ops' `.git/objects` are owned by root (created 2026-09-19 to 2026-09-28, before this session), so git cannot write objects hashing into them. The litellm branch's trees do, deterministically. The crunchy and renovate commits happened to avoid them. A workaround that packed the objects into the repo was refused by the permission classifier and not pursued.
    - The changes are staged in the `atlas/litellm` worktree, and a patch plus the commit message are saved in the scratchpad.
    - **Owner:** `sudo chown -R "$USER": /mnt/c/Users/ekenh/home-ops-upgrade/.git/objects`, then commit in that worktree with the saved message.
  - `rerank` in the key routes to `hindsight-tei-reranker.llm`, the **shared** Hindsight's TEI sidecar. Atlas's reranking therefore depends on `llm/hindsight` staying up (the configmap says the same for memini).
  - The ClusterSecretStore is named `litellm-key-secrets` (after `crunchy-pgo-secrets`), not `litellm-keys` as the research note suggested, to avoid confusion with the `litellm-keys` Flux Kustomization.
- **Credentials:** none needed.
- **Next:** the owner fixes the object-store ownership and commits `atlas/litellm`, reviews the three branches, then pushes and opens them in the order in `docs/runbooks.md`. After PR 1, run the `vector` step. PR 4 (`atlas-hindsight` release) and PR 6 (the app) are later tickets.
