# Runbooks

One-off steps the owner runs by hand, in the order they're needed. Each step says where it comes from; the decisions behind them are in `docs/decisions.md` (deploy shape, ticket 09).

## Home-ops PR merge order

Home-ops (`github.com/ekenheim/home-ops-upgrade`) PRs **auto-merge and deploy**. Open each one only after the previous step has reconciled. The agent prepares and validates each branch locally (yamllint, kubeconform, flux-local); the owner reviews, pushes and opens it.

| # | Branch / step | What it does | Done when |
|---|---|---|---|
| 1 | `atlas/crunchy-users` | PGO users and databases `atlas` and `atlas-hindsight` | `kubectl -n database get secret postgres-pguser-atlas postgres-pguser-atlas-hindsight` finds both |
| 1b | [`vector` extension](#vector-extension-in-atlas-hindsight) (by hand) | `CREATE EXTENSION vector` in `atlas-hindsight` | `\dx vector` lists it |
| 2 | `atlas/litellm` | aliases `atlas-extract` / `atlas-reflect` → MiniMax-M3, the `atlas` virtual key, the `litellm-key-secrets` ClusterSecretStore (serves `datasci` only), and the PRIVACY-note exception. **The configmap edit restarts LiteLLM via reloader**, a short outage for every caller, so merge at a quiet time. | the key and store are ready (see below) |
| 3 | `atlas/renovate` | automerge off for `kubernetes/apps/datasci/atlas/**` and `ghcr.io/ekenheim/atlas` | merged to `main`; Renovate reads its config from there |
| 4 | the `atlas-hindsight` release | the dedicated Hindsight in `datasci` | its API is ready in-cluster |
| 5 | outside Git | [MinIO archive provisioning script](#archive-bucket-provisioning), the R2 bucket `atlas-archive-offsite` and its token, credentials into the Bitwarden item `atlas` | the script reports the bucket locked |
| 6 | the `atlas` app release | api, worker, R2 copy CronJob, route | the smoke script passes |

Why this order:
- Step 1b needs the database from step 1, and it must run before Hindsight's first boot (step 4).
- Step 3 goes before step 4 so that no Renovate bump inside `datasci/atlas/` can ever auto-merge.
- Step 6 needs the first Atlas image on GHCR.

Checks after step 2:

```sh
kubectl -n llm get litellmvirtualkey atlas
kubectl -n llm get secret litellm-key-atlas
kubectl get clustersecretstore litellm-key-secrets   # STATUS Valid, READY True
```

What later releases rely on from steps 1–2:
- **Postgres credentials:** PGO writes `postgres-pguser-atlas` and `postgres-pguser-atlas-hindsight` in `database`. Read them through the `crunchy-pgo-secrets` ClusterSecretStore.
- **LiteLLM key:** an ExternalSecret in `datasci` with store `litellm-key-secrets` and `remoteRef: {key: litellm-key-atlas, property: api-key}`. The store's Role can read only that Secret, and its `conditions` admit only `datasci`.
- **Flux dependencies:** the `atlas` Kustomization `dependsOn` `litellm-stores` (the store) and `litellm-keys` (which mints the key), plus crunchy and external-secrets.

## `vector` extension in `atlas-hindsight`

**When:** once, after step 1 has merged and PGO has created the `atlas-hindsight` database, and before the `atlas-hindsight` release (step 4) first boots. Re-running it is harmless.

**Why by hand:** the `atlas-hindsight` role owns its database, but PG16 doesn't trust `vector` for a non-superuser, so a superuser must create it. An init container would put the cluster superuser credential into `datasci`. That is the same trade-off as the shared `hindsight` database (home-ops `kubernetes/apps/llm/README.md`).

```sh
P=$(kubectl get pods -n database -l postgres-operator.crunchydata.com/role=master -o jsonpath='{.items[0].metadata.name}')
kubectl exec -n database "$P" -c database -- psql -U postgres -d atlas-hindsight -c 'CREATE EXTENSION IF NOT EXISTS vector;'
kubectl exec -n database "$P" -c database -- psql -U postgres -d atlas-hindsight -c '\dx vector'
```

The last command should list `vector`. If `psql` says the database doesn't exist, PGO hasn't reconciled step 1 yet; wait and retry.

The `atlas` database needs no extension.

## Archive bucket provisioning

**When:** rollout step 5, before the `atlas` app release. Re-running it is safe: a second run changes nothing and ends with `No changes: already provisioned.`

**What it does:** `scripts/provision_archive.py` (decision: `docs/decisions.md`, archive durability, ticket 10) creates, as the MinIO root user:
- **Bucket:** `atlas-archive`, with object lock enabled at creation (which implies versioning), and a default retention of **GOVERNANCE, 3650 days**.
- **Policy:** `atlas-archive-app`, scoped to that bucket. It allows only what the archive does: get, put, head and list. It explicitly denies `s3:BypassGovernanceRetention`, and grants no delete.
- **User:** `atlas`, with that policy attached. The root user keeps the Governance escape hatch; the `atlas` user can't delete or shorten a locked version.

It prints the `atlas` user's credentials **once**, to the terminal, and never writes them to disk. It refuses, and exits 1, rather than change anything it didn't create: an existing bucket without object lock, or with a different default retention.

**Prerequisites:**
- a checkout of this repo with `uv sync` done. The `minio` package is a dev dependency, not in the app image.
- network access to the cluster's S3 API at `https://s3.<domain>`
- the MinIO root user and password

Keep the root credentials out of shell history and arguments. Read them into the environment:

```sh
read -rp 'MinIO root user: ' MINIO_ROOT_USER
read -rsp 'MinIO root password: ' MINIO_ROOT_PASSWORD; echo
export MINIO_ROOT_USER MINIO_ROOT_PASSWORD
uv run scripts/provision_archive.py --endpoint https://s3.<domain>
unset MINIO_ROOT_USER MINIO_ROOT_PASSWORD
```

The first run ends with a block like this:

```text
Store these in the Bitwarden item `atlas` now; they are not shown again and are not saved anywhere:
  S3_ENDPOINT_URL=https://s3.<domain>
  S3_BUCKET=atlas-archive
  S3_ACCESS_KEY_ID=atlas
  S3_SECRET_ACCESS_KEY=<40 characters>
```

**Store it in Bitwarden:**
- Copy the four values into the Bitwarden item `atlas`, as fields with exactly those names. The app release's ExternalSecret maps them to `ATLAS_S3_*`. `ATLAS_ARCHIVE_BACKEND=s3` is plain config in the release.
- Don't pipe the output into `tee` or a file.
- Clear the terminal scrollback once the item is saved.

**Done when:** a second run prints `object lock GOVERNANCE 3650 days (ok)` and `No changes: already provisioned.`

**Lost or leaked credentials:**
- Run it again with `--rotate-secret`. That issues and prints a new secret for the existing user and revokes the old one.
- Update the Bitwarden item, then restart the api and worker once the ExternalSecret has refreshed.

**Options:**
- `--bucket`, `--user`, `--policy` (default `<bucket>-app`) and `--retention-days` (default 3650). The mode is always Governance.
- The script never changes the lock of an existing bucket. Changing the retention is a deliberate root action, done by hand.

**Against the Compose Silo (dev):**
- the same command, with `--endpoint http://127.0.0.1:59000` and the root `atlas-dev` / `atlas-dev-secret` from `compose.yaml`
- use a throwaway `--bucket` and `--retention-days 1`, because locked versions can't be removed without the root bypass. `tests/integration/test_archive_provisioning.py` does exactly this.

## Live test suite (Phase 2 gate)

**What:** `tests/live/test_phase2_gate_live.py` runs the Phase 2 gate scenarios end to end against a real Hindsight 0.10.1 with MiniMax-M3 (thinking off) through LiteLLM. It is **never run in CI** (spec Part B, Testing Decisions: live tests; `docs/decisions.md`). `scripts/live-tests.sh` brings up the stack, runs the suite, records the results and, if asked, tears down.

**When:** by hand, with the owner's go-ahead. It is worth running after changes to retention or research, and before a release that touches them. **A live run spends MiniMax quota.**

**Prerequisites:**
- LiteLLM settings: `ATLAS_LITELLM_URL`/`ATLAS_LITELLM_API_KEY` in the environment, or the repo `.env`'s `LITELLM_URL`/`LITELLM_API_KEY` (the spike's names, read CRLF-safe and never printed).
- Docker. The runner starts `postgres-app` only if nothing answers on 55432; it never touches Silo.
- Routed aliases. Until the home-ops `atlas/litellm` step routes `atlas-extract`/`atlas-reflect`, pass `--model MiniMax-M3`. Without it, the preflight refuses and names the missing alias.

**Opt-in:** two locks, both required.
- the `live` marker: the pytest addopts in `pyproject.toml` deselect it
- `ATLAS_LIVE_TESTS`: `1` for a live run, `rehearse` for the fakes. Without it, `pytest -m live` still skips every scenario.

A live run's preflight refuses (pytest exit status 4) when:
- `CI` is set
- Hindsight isn't healthy, or isn't 0.10.1
- an alias isn't routed in LiteLLM
- the app Postgres is unreachable

The preflight reads only `/health`, `/version` and `/model/info`, so it calls no model. The runner also asks for confirmation before a live run, unless `--yes`.

**Steps, cheapest first:**

1. Rehearse, which is free. It runs the same scenarios against the recorded Hindsight fake and the `/model/info` fake on localhost. No container, no `.env`, no quota. It checks the suite's own wiring, not Hindsight:
   ```sh
   scripts/live-tests.sh --rehearse
   ```
2. Check the stack without spending quota. This starts the Compose `hindsight` profile and runs the preflight. It then applies the template, config only; it skips the import if the template has mental models, whose import would queue refreshes. Finally it ingests the fixtures with retention off. The LLM-backed scenarios are skipped.
   ```sh
   scripts/live-tests.sh --stop-before-llm --model MiniMax-M3
   ```
3. Run it live:
   ```sh
   scripts/live-tests.sh --model MiniMax-M3            # small profile: the two 10-Qs
   scripts/live-tests.sh --model MiniMax-M3 --profile full --down
   ```

**Options:**

| Option | Default | What it does |
|---|---|---|
| `--stack compose` | yes | The Compose `hindsight` profile on `127.0.0.1:58888`, the production-like config (per-role aliases). |
| `--stack spike` | | `spikes/hindsight/run.sh MiniMax-M3 '{"thinking":{"type":"disabled"}}'` on `:8888`. It uses one alias and needs `.env`. |
| `--stack none` | | Uses the Hindsight at `ATLAS_LIVE_HINDSIGHT_URL` as it is. |
| `--profile small` | yes | `ATLAS_LIVE_FORMS=10-Q`: about 18k characters, which costs roughly what the extraction bake-off did. The 10-Qs are mostly cover pages and financial tables, so expect few facts, and possibly zero-fact sections. |
| `--profile full` | | Every recorded filing (`10-K,10-Q,8-K`): about 470k characters. Est. **~40 min of retain and ~1M input tokens**, extrapolated from the bake-off's rate and not measured. |
| `--down` | | Stops and removes the Hindsight containers afterwards, even when the suite fails. The volume is kept. |
| `--purge` | | With `--down`, also deletes the `hindsight-db` volume. Each run uses a new bank, `atlas-live-<UTC stamp>`, so banks otherwise accumulate there. |
| `--keep-db` | | Keeps the run's app database, `atlas_live_*`, which is otherwise dropped. |
| `--results DIR` | `.scratch/live-runs/<stamp>-<mode>/` | Where the results go (gitignored). |
| `--dry-run` | | Prints the commands and runs nothing. |

Further knobs are environment variables, all in `tests/live/stack.py`:
- `ATLAS_LIVE_RETAIN_DEADLINE_SECONDS` (default 3600)
- `ATLAS_LIVE_CONSOLIDATION_WAIT_SECONDS` (default 300)
- `ATLAS_LIVE_BANK_ID`

**What it checks.** The scenarios share one run, in this order:
- preflight
- the bank template is applied (the bank config matches the file)
- both companies' fixtures are ingested as parsed Source Versions
- every section reaches a final state through completed operations, waiting out queue pauses
- cross-company recall returns both companies, with every memory resolved to its Source Version, section offsets and `available_at`
- a reflect over the photonics theme completes with a recorded run. None of its citations is broken, and every cited memory resolves. **Unverified chunks and quotes are reported, not failed.**
- zero-fact sections show `zero_fact` after exactly one reprocess, and match the metric. If the run produced none, this scenario is **skipped** and says so.
- Hindsight's LLM request stats, for the record

The model's answers aren't scripted, so the suite asserts only what must hold for any correct answer.

**Results:** `summary.md` (to copy into the log), `results.json` (everything seen), `junit.xml` and `pytest.log`.

**Exit status:**

| Status | Meaning |
|---|---|
| 0 | passed |
| 1 | a scenario failed |
| 2 | a usage error, or not confirmed |
| 4 | refused by the preflight: nothing was sent to a model |

**Record it:** add an entry to `docs/implementation-log.md` from `summary.md`. The entry says:
- the date and the stack
- the aliases and their routed deployments
- the profile
- each scenario's outcome
- the unverified citations and zero-fact sections
- the token usage

It also says plainly which paths ran live. A rehearsal is not a live run.

## Live extraction smoke test (ticket 28)

**What:** `tests/live/test_extraction_smoke_live.py` runs the Investigator on real MiniMax output over three recorded EDGAR filings and reports how its Claims fare. It measures whether the Assertion span check rejects true Claims as `quote_mismatch` because the model counts characters poorly. **Never run in CI.** `scripts/live-extraction-smoke.sh` runs it and writes the report.

**When:** by hand, with the owner's go-ahead. **A live run spends a little MiniMax quota:** at most 6 chat completions (3 calls, each with at most one repair; the cap is 10), each extraction's run capped at 40,000 tokens, and one attempt per job.

**What it runs.** It creates a throwaway app database (`atlas_live_extract_*`), ingests the Lumentum and Coherent fixtures, and seeds the universe plus NVIDIA. Then it runs three `extract_claims` jobs, each with at most 4 passages in one call:
- the Lumentum FY2026 10-K's Item 1
- the Lumentum Q4 FY2026 release (8-K EX-99.1)
- the Coherent FY2026 10-K's entity-tagged passages (NVIDIA, Lumentum)

The Lumentum documents name no other known company, so a stubbed recall picks their sections. No Hindsight is needed: the recorded Hindsight fake serves on localhost for the ingest and the run record, and the run's Hindsight version is the fake's. Only the Investigator's calls go to LiteLLM (`--model`, default `MiniMax-M3`, thinking off).

**Opt-in:** the `live` marker and `ATLAS_LIVE_TESTS` (`1` live, `rehearse` the scripted LiteLLM fake). LiteLLM settings come from `ATLAS_LITELLM_URL`/`ATLAS_LITELLM_API_KEY` or the repo `.env` (read CRLF-safe, never printed). The preflight refuses (exit status 4) under `CI`, without LiteLLM settings, or when the model isn't routed in LiteLLM (`/model/info`, no model call).

**Steps:**
```sh
scripts/live-extraction-smoke.sh --rehearse            # free: the scripted fake, localhost only
scripts/live-extraction-smoke.sh --model MiniMax-M3    # live; asks first unless --yes
```
Options: `--keep-db`, `--results DIR` (default `.scratch/live-runs/<stamp>-extraction-<mode>/`, gitignored), `--dry-run`.

**The report:** `summary.md` and `results.json` contain:
- per extraction: its passages, job status, calls and tokens
- per Claim: predicate, outcome, reason code
- for each `quote_mismatch`: whether the quote occurs in its passage `exactly_once`, `multiple` times or `not_at_all`, exactly and after folding whitespace, typographic quotes and dashes
- for a quote found exactly once: what the later checks (both parties named, directional language) would make of it if located

The totals give the mismatch share of the Claims that reached the span check. If it exceeds 20%, put the quote-location decision to the owner with those numbers (ticket 28). The live test asserts only the call cap and that each job succeeded with passages; the rehearsal also checks the report's classification of scripted answers.

**Record it** in `docs/implementation-log.md` from `summary.md`, and say plainly whether it was live.

## Replay banks (ticket 22)

**What:** `POST /api/v1/replay-jobs` replays the pipeline at a cutoff in an isolated `atlas-replay-<id>` bank and deletes the bank afterwards (`docs/decisions.md`, "Replay banks"). In CI it runs only against the recorded Hindsight fake (`tests/integration/test_replay.py`, the leakage gate). There is no `scripts/live-verify.sh` on this branch, so the live run is this manual procedure.

**Where:** the **local** Hindsight only: the Compose `hindsight` profile (or a throwaway server), never the owner's shared Hindsight. `ATLAS_REPLAY_HINDSIGHT_URL` is separate from `ATLAS_HINDSIGHT_URL` for that reason; don't point it at the shared server.

**Cost:** each chosen Source Version is one retain batch (all its sections; triage is bypassed), then one consolidation and, per question of the set (2 in `default`), a recall and a reflect: LLM work on the local Hindsight's model (MiniMax via LiteLLM). Keep `ATLAS_REPLAY_MAX_SOURCE_VERSIONS` small (default 3) and scope by `company_ids`. The replay's operations count against the `codex` budget. **Run it only with the owner's go-ahead.**

**Steps (opt-in live run):**

1. Start the local Hindsight: `docker compose --profile hindsight up -d --wait` (needs `ATLAS_LITELLM_URL`/`_API_KEY`).
2. Point the API and a worker at it, with the research database that holds the Source Versions:
   ```sh
   export ATLAS_REPLAY_HINDSIGHT_URL=http://127.0.0.1:58888
   ```
3. Ask for a replay (the API from `uv run atlas api` listens on 8000; the Compose `api` on 58080) with a cutoff before a source you know was published later (a future-dated source for the cutoff), e.g. for one company:
   ```sh
   curl -s -X POST localhost:8000/api/v1/replay-jobs -H 'content-type: application/json' \
     -d '{"cutoff": "2025-12-31T23:59:59Z", "company_ids": ["<company id>"], "max_source_versions": 2}'
   ```
   The response lists the Source Versions the replay may see. Check the later source is not among them.
4. Run the worker until the replay is done: `uv run atlas worker --once` (it runs one step per attempt and requeues itself, so one pass normally finishes it; a quota pause resumes on a later pass).
5. Read `GET /api/v1/replay-jobs/{id}`: `status` `completed`, `leakage.future_accepted` **0**, `bank_deleted_at` set. `consolidation.status` `timed_out` means the answers ran before consolidation finished; note it with the results.
6. Check the bank is gone on the local Hindsight: `curl -s localhost:58888/v1/default/banks | grep atlas-replay` finds nothing. If a replay reports `bank_delete_error`, delete the bank by hand (`curl -X DELETE localhost:58888/v1/default/banks/atlas-replay-<id>`) and record it.

`POST /api/v1/replay-jobs/{id}/cancel` stops a replay; its next step deletes the bank.

## Live verification (ticket 32)

**What:** `tests/live/test_live_verify.py` checks each Phase 3–6a part against the real services, in one small, bounded run that always writes a report. `scripts/live-verify.sh` runs it. **Never run in CI.**

**When:** by hand, with the owner's go-ahead (given 2026-09-30). A live run spends MiniMax quota and calls SEC, GLEIF, OpenFIGI, the FCA NSM, the AMF and SearXNG.

**The parts.** Each part is one test, can be chosen with `--only`, and has its own budget:

| Part | What it does | Chat calls | Retain ops |
|---|---|---|---|
| `sec` | For each `--companies` company, a live SEC ingest of its `--limit` newest filings (default 2; 10-K/10-Q/8-K per config) with triage on. At most `--max-retains` versions are retained per company. It waits for the operations and consolidation, then runs a cross-company recall and one reflect. The report gives citations resolved, unverified and broken, and the companies cited. | 12 | 25 |
| `exchanges` | IQE (FCA NSM) and Soitec (AMF): discovery and one document each through the fetch gate (`ATLAS_EXCHANGE_LIVE`, generic User-Agent), with the gate's decisions. Retention is off. | 0 | 0 |
| `tradingview` | Ticket 31's `tradingview_catalog` (`{"company": <slug>}`) for the first `--companies` company with a `tradingview_symbol`, then the `tradingview_transcripts` job the catalog enqueues. At most two tool calls per job, so at most two transcripts; they are archived as Tier B Source Versions, not retained. The report gives the catalog's entries by category, the news leads and each transcript. Skipped, saying what to do, unless `ATLAS_TRADINGVIEW_ENABLED=true` (from the environment or `.env`) and there is a token: the token file `atlas tradingview login` wrote (`ATLAS_TRADINGVIEW_TOKEN_FILE`, relative to the repo root) or `ATLAS_TRADINGVIEW_ACCESS_TOKEN`/`_REFRESH_TOKEN`. A rehearsal serves the TradingView fake (`tests/fakes/tradingview.py`) with a token file of its own. | 0 | 0 |
| `discovery` | The Scout (3 queries) and SearXNG give leads. `propose_candidates` (the mention extractor, then live entity resolution) gives Candidates. Skipped without SearXNG. | 8 | 0 |
| `relationships` | `extract_claims` on the recorded Coherent FY2026 10-K (the NVIDIA supply agreement; 8 passages, one call), then `review_relationships` (the Reviewer). | 6 | 0 |
| `investigation` | One investigation on Coherent and Lumentum (their recorded filings), run to its stop. Then a Hypothesis draft and a scenario: the Financial Analyst's table, or an all-estimated researcher table if the Analyst proposed none. The scenario is recomputed and resent, and both must be byte-identical. Finally version 1 goes through the publish gate (ticket 20): `evidence_ready`, then `GET .../publish-gate`. When the only failure is `relationship_not_approved`, the harness plays the owner: it approves each named edge through `POST /api/v1/relationships/{id}/review` with a note saying so, and the report lists them under `owner_step` (a harness decision, not a human one). It then publishes when the gate allows and reads the Research Snapshot back (`GET /api/v1/snapshots/{id}`, re-hashed on read). A gate the owner can't open (no falsifier, no unresolved question, an Assertion not machine-reviewed) is reported, not forced. Skipped without SearXNG. | 14 | 0 |
| `identity` | `atlas companies resolve --company lumentum --company coherent` (live SEC, GLEIF, OpenFIGI), then the pending reviews. | 0 | 0 |

**Caps.** Atlas reaches LiteLLM and Hindsight only through two counting proxies on localhost (`tests/live/verify.py`, `CappedProxy`). The part is aborted, and reported `aborted`, when either of these happens:
- a chat completion beyond the part's budget, or beyond the run's cap of 40 (`--max-chat-calls N` lowers it), is refused with HTTP 400
- a retain batch beyond 25 is refused with HTTP 400

The leftover jobs are then failed, so they don't spill into the next part. Settings bound the rest: 30 sections per triage call, `--max-retains`, a 150,000-token budget per run, 8 passages per extraction, 3 discovery queries, and at most 5 leads and 6 documents per investigation. Each part reports two sets of usage figures:
- the proxies' counts
- what the database recorded since the part began: `llm_call` calls and tokens, `role_call` by role and status, and `hindsight_operation` by kind and status

Hindsight's own LLM use (retain extraction, consolidation, reflect) runs on the Hindsight side and isn't in the 40. The report adds the bank's `llm_request_stats` after a live `sec` part.

**Stack.** The stack is `tests/live/stack.py`'s, with the same two locks as the live suite: the `live` marker and `ATLAS_LIVE_TESTS` (`1` live, `rehearse` fakes). The preflight refuses (exit status 4) in these cases, before any model call:
- under `CI`
- without LiteLLM settings
- when Hindsight isn't 0.10.1
- when an alias or the role model isn't routed

The default `--stack cluster` uses the owner's cluster Hindsight (`HINDSIGHT_URL`/`HINDSIGHT_API_KEY` in `.env`, else `~/.hindsight/config`). It creates a throwaway `atlas-live-<stamp>` bank from the bank template, which is always deleted at the end unless `--keep-bank` is given. `--stack compose` uses the Compose Hindsight on :58888.

The run has one throwaway app database (`atlas_live_*`, dropped unless `--keep-db`) and archive. The universe is seeded as the repo's plus NVIDIA. The script reads its settings from the environment, else `.env`. It reads them CRLF-safe and never prints them:
- `ATLAS_LITELLM_*` or `LITELLM_*` (required)
- `ATLAS_SEC_USER_AGENT` (required by `sec`, `discovery` and `identity`)
- `ATLAS_SEARXNG_URL` or `SEARXNG_URL`
- `ATLAS_EXCHANGE_USER_AGENT`
- `ATLAS_TRADINGVIEW_*`

**Steps:**
```sh
scripts/live-verify.sh --rehearse                        # free: every part against the fakes
scripts/live-verify.sh --only sec --companies lumentum --limit 1   # one live part, small
scripts/live-verify.sh                                    # the full live run; asks first unless --yes
```
Other options: `--model M` (default `MiniMax-M3`, also Atlas's extract/reflect aliases), `--results DIR` (default `.scratch/live-runs/<stamp>-verify/`, gitignored) and `--dry-run`.

**The report:** `summary.md` has a table with each part's result (passed, failed, aborted, skipped with the reason), chat calls and retain operations against the budget, recorded LLM calls, tokens and seconds. After the table come each part's numbers. `results.json` has everything.

A rehearsal's model answers are scripted (`RehearsalModel`), and so are its SearXNG and identity responses (the fakes over `tests/fixtures/`). It checks the harness, never a model. In a rehearsal, the `sec` part uses the companies with recorded EDGAR fixtures (Lumentum, Coherent) and lists the others.

**Record it** in `docs/implementation-log.md` as LIVE, from `summary.md`, with exactly which parts ran. Fix what failed.

## Triage audit (ticket 33)

**What:** `atlas triage audit` measures how often retention triage skips a section that a full reading would retain (rules in `docs/decisions.md`, "Measuring what triage misses"). It draws a seeded, stratified sample of skipped sections and enqueues a `triage_audit` job; the worker gives each sample's archived text, whole, to the full-section judge (MiniMax through LiteLLM). It needs LiteLLM and Hindsight configured, as triage does, and spends MiniMax quota (paced by the `minimax` budget), so a live audit runs with the owner's go-ahead (given for the first, 2026-09-30).

**Where to run it.** Anywhere with the deployment's settings and a worker running:
- **On the cluster:** in the Atlas API or worker pod (`kubectl exec` into it), against the production database and archive: `atlas triage audit --company lumentum --sample 40 --seed 1`, then again for `coherent` (or leave out `--company` for every company). The cluster worker judges it; add `--wait` to print the summary when it is done, or read `GET /api/v1/triage/audits/{id}` later.
- **On a live-verify database:** run `scripts/live-verify.sh --only sec --companies lumentum,coherent --keep-db --keep-bank` (triage runs on the live filings), then point `ATLAS_DATABASE_URL` and `ATLAS_ARCHIVE_ROOT` at the kept `atlas_live_*` database and its archive, with the same `ATLAS_LITELLM_*` and `ATLAS_HINDSIGHT_URL`, and run `atlas triage audit --sample 40 --wait` alongside `atlas worker`. Also set `ATLAS_HINDSIGHT_BANK_ID` to the live run's bank (its template application is recorded in that database; the run record needs it), `ATLAS_HINDSIGHT_VERSION=0.10.1` (the cluster route exposes only `/v1`) and `ATLAS_MENTAL_MODEL_REFRESH_AT=` (empty: no scheduled refreshes against the deleted bank). Copy the archive out of pytest's temp directory first (`/tmp/pytest-of-<user>/pytest-<n>/verify0/archive`); pytest keeps only its last three. Drop the database and the bank afterwards.

**Cost.** One judge call per sample, more for a section past 60,000 characters (`ATLAS_TRIAGE_JUDGE_MAX_CHARS`: a 143,000-character Item 1A is up to three calls). A 40-sample audit is about 40 to 60 calls and, with long Items, a few hundred thousand input tokens: it can take more than one 5 h `minimax` window at the default 400,000-token budget. `--backfill` keeps it out of the interactive reserve. `GET /api/v1/queue` shows it held by the budget.

**Reading it.** `GET /api/v1/triage/audits/{id}` (or `--wait`'s output):
- `summary.miss_rate` with `wilson_low`/`wilson_high`: of the judged samples, the share triage skipped but the judge would retain. With 40 samples the interval is wide (0 misses: 0 to 8.8%); read it as "at most", not a point value.
- `weighted_miss_rate`: the same, each stratum weighted by its share of all skipped sections (the sample over-represents rare strata on purpose).
- `by_length_band`: where the misses are. Misses in `10k-50k` and `50k-plus` with `windows_read` well below `windows_total` mean triage's windows are too few for long Items (raise `ATLAS_TRIAGE_WINDOWS_PER_SECTION`); misses in `under-2k` mean the rubric or the model, not the windows.
- `by_method`: misses by `rule` point at a boilerplate rule; by `inherited`, at an earlier decision copied forward.
- `misses_by_judge_category` and `examples`: what was missed (the anchor, heading and the judge's reason). Open an example in the source viewer; if it is a real miss, retain the section on demand (`POST /api/v1/source-versions/{id}/sections/{anchor}/retain`). The judge can be wrong too: check a few by hand before changing triage.
- `unjudged`: samples the judge gave no usable answer for (their `error`); re-run with a new seed if there are many.

**Record it** in `docs/implementation-log.md` as LIVE: the command, the audit ID, the sample, the miss rate with its interval, the misses by band and category, and a note on each example.

## EDGAR availability corrections (after deploying migration `0012`)

Source Versions ingested before the EDGAR dissemination rule (docs/decisions.md, 2026-09-29) are dated at acceptance even when EDGAR held the filing to the next business day. After `atlas migrate` has applied `0012`, run once, with the app's settings:

```
atlas ledger correct-availability
```

It prints `{"corrected": [<source version ids>], "out_of_calendar": [...]}`. It is idempotent (a second run corrects nothing), appends one audited row per affected version to `source_version_availability_correction`, and never edits a version. A version in `out_of_calendar` has dates beyond the EDGAR holiday table (`backend/atlas/sources/edgar_calendar.py`): extend the table and run it again.

## Evidence Family backfill (after deploying migration `0016`)

Parsed Source Versions recorded before `0016` have no Evidence Family. After `atlas migrate`, run once, with the app's settings:

```
atlas ledger assign-families
```

It prints `{"assigned": [<source version ids>], "families_created": N}`, oldest ingested first, each version in its own audited transaction (`evidence_family.created`, `evidence_family.member_added`). It is idempotent. `ATLAS_EVIDENCE_FAMILY_MAX_HAMMING_DISTANCE` (default 3) is the threshold new families are founded with.

The holiday table ends on 2027-12-31. When SEC publishes its next EDGAR Calendar (<https://www.sec.gov/submit-filings/filer-support-resources/edgar-calendar>), add that year and any announced closures, and move `EDGAR_CALENDAR_RANGE`. Past the end, ingest of a new filing fails with `EdgarCalendarRangeError`.

## XBRL normalization backfill (pilot-fixes ticket 07)

Companyfacts Source Versions recorded before XBRL normalization existed (0.1.x) have no financial observations, so `GET /api/v1/companies/{id}/financials` is empty and the Financial Analyst is sent `figures: []`. Check first: `atlas_financial_normalizations_total` is 0 for both outcomes, or `GET /api/v1/companies/{id}/financial-observations` is empty for an SEC company with a `xbrl_companyfacts` Source Document. Then run once, with the app's settings (the worker's environment: `ATLAS_SEC_LIVE=true` and `ATLAS_SEC_USER_AGENT`, since each company's submissions index is fetched from SEC to map every fact to its filing's acceptance time):

```
atlas financials normalize            # every company
atlas financials normalize --company lumentum
```

For each company with a companyfacts document it normalizes the latest version unless the current normalizer (`xbrl-normalizer-v1`) already did, and prints `{"companies": [{"company", "source_version_id", "status", "detail"}]}`, by slug. `status` is `succeeded` (`detail` has `facts_read`, `observations_created` and the `financial_normalization` ID), `already_normalized`, `failed` (recorded in `financial_normalization_failure`, audited, counted in `atlas_financial_normalizations_total{outcome="failed"}`; `detail` has the error) or `submissions_unavailable` (the submissions request failed; nothing was attempted or recorded). One company's failure doesn't stop the others; the exit code is 1 if any company is `failed` or `submissions_unavailable`, 2 for an unknown `--company`. It is idempotent: a second run reports `already_normalized` and changes nothing, and retries only what failed.

Afterwards, `GET /api/v1/companies/{id}/financials?as_of=` returns figures, and the next investigation's Financial Analyst is sent them. Ingests normalize a pending version themselves from now on, whether or not they fetch companyfacts again, so this is a one-off per normalizer version.

## Re-parsing recorded filings (after deploying migration `0046`)

Source Versions recorded under an earlier parser (`text-v2`, `html-text-v1`) keep that parse; page-break artifacts stay in their text, so a quote across a page break is refused `quote_mismatch` there. To give them a `text-v3` parse (docs/decisions.md, "Re-parsing recorded Source Versions"), after `atlas migrate` has applied `0046`, with the app's settings:

```
atlas ledger reparse --company coherent     # one company; omit --company for every company
atlas worker --once                          # or let the running worker take the job
```

`reparse` prints the enqueued job (kind `reparse`, not pausable, no LLM or Hindsight use). `GET /api/v1/jobs/{id}` shows its artifacts: `selected`, `inserted` and one entry per new parse (`source_parse_id`, the version, the recorded parser version, status, content hash, `same_text_as_recorded`). Each new parse is audited (`source_parse.created`). It is idempotent: a second run selects nothing that already has a `text-v3` parse (`inserted: 0`).

To check a version: `GET /api/v1/source-versions/{id}` lists `parses` (the recorded one first; its own `parser_version` and `content_sha256` are unchanged) and `current_parser_version`; `GET /api/v1/source-versions/{id}/content?kind=parsed&parser_version=text-v3` serves the re-parse's text.

What changes afterwards: new `extract_claims` runs (and investigations' Investigator tasks) read the re-parse, and their Claims and Assertions record `parser_version: text-v3`. Existing Assertions keep their `text-v2` spans; a better quote on the new parse is a new Assertion, and the owner may supersede the old one through the normal review. **Memory is not re-retained:** recall, reflect, triage and the Skeptic still read the recorded parse (retaining the re-parse is designed, not built). Nothing to undo: the migration's downgrade refuses once a re-parse exists, and the recorded parses were never touched.

## Universe rollout and quota budgets (ticket 27)

The owner's ChatGPT/Codex subscription (spent by the shared Hindsight's retain, consolidation and mental models) and MiniMax subscription (spent by Atlas's roles through LiteLLM) each renew in rolling 5-hour windows. The queue rations both (`atlas.jobs.budget`; rules in `docs/decisions.md`, "Quota-window pacing"), so the ten companies not yet ingested come in **one company per window**, never in one bootstrap like the 2026-09 incident (1,397 operations, ~1.27M Codex tokens in minutes).

### Reading the budget view

`GET /api/v1/queue` has one `budgets` entry per provider:

```
{"provider": "codex", "unit": "operations", "window_seconds": 18000,
 "used": 28, "budget": 40, "backfill_limit": 28,
 "interactive_held": false, "backfill_held": true,
 "interactive_resumes_at": null, "backfill_resumes_at": "2026-09-30T02:14:05Z",
 "kinds": ["reflect", "refresh_mental_model", "reprocess", "retain"]}
```

- `used`: what the last `window_seconds` spent: Hindsight operations submitted (codex) or recorded LLM tokens (minimax).
- `backfill_held`: backfill jobs of `kinds` wait; `backfill_resumes_at` is when enough usage leaves the window for them to run again. `interactive_held` is the same for everything (the owner's own work included) once the whole budget is spent.
- Each `pending` kind shows `budget_held`, the queued jobs the budget holds now. `pause` is the separate 429/outage backstop: if it shows a `quota` pause while `used` is well under `budget`, the budget is too high for the subscription.
- Metrics: `atlas_budget_used{provider,unit}`, `atlas_budget_limit{provider,job_class}`, `increase(atlas_budget_usage_total[5h])` and `atlas_queue_jobs_held_by_budget{provider,kind,job_class}`.

### Tuning

Defaults are deliberately low: `ATLAS_CODEX_BUDGET_OPERATIONS=40`, `ATLAS_MINIMAX_BUDGET_TOKENS=400000`, `ATLAS_BUDGET_WINDOW_HOURS=5`, `ATLAS_BUDGET_INTERACTIVE_RESERVE=0.3` (backfill stops at 70%: 28 operations, 280,000 tokens). Raise a budget only after a few windows in which the provider's own usage page shows headroom at the end of a window and no `quota` pause was entered (`atlas_queue_pauses_total{error_class="quota"}` flat). Raise in steps of about 25%, one provider at a time; lower it at once after a quota pause. The reserve is what the owner's own investigations can still use when a backfill has run to its limit. `ATLAS_BACKFILL_WINDOW` is optional: empty (the default) lets backfill run whenever the budget allows; set ranges (for example `01:00-07:00,13:00-15:00`, in `ATLAS_BACKFILL_TIMEZONE`) only to keep backfill out of hours the owner works in.

### Rollout, one company per window

Done: Lumentum, Coherent. Remaining, smallest filer first (a company's own ingest plan shows its real size before the next is started; reorder if a plan surprises):

| # | Company | Path | How |
|---|---|---|---|
| 1 | AXT (`axt`) | SEC 10-K/10-Q/8-K | `atlas ingest --company axt --backfill --max-retains 20` |
| 2 | Applied Optoelectronics (`applied-optoelectronics`) | SEC | same, `--company applied-optoelectronics` |
| 3 | Fabrinet (`fabrinet`) | SEC | same |
| 4 | MACOM (`macom`) | SEC | same |
| 5 | Ciena (`ciena`) | SEC | same |
| 6 | Marvell (`marvell`) | SEC | same |
| 7 | STMicroelectronics (`stmicroelectronics`) | SEC 20-F/6-K (many 6-Ks): largest, last of the SEC filers | same |
| 8 | Zhongji Innolight (`innolight`) | HKEXnews is blocked (terms) | manual import only: `atlas sources import --company innolight ...`, a few documents per window |
| 9 | IQE (`iqe`) | FCA NSM | waits for ticket 05's adapter |
| 10 | Soitec (`soitec`) | AMF info-financière API (`exchange:amf`): only English documents are retained | `atlas ingest --company soitec --backfill --max-retains 20` with `ATLAS_EXCHANGE_LIVE=true` (0.5 requests/s: a two-year backfill of ~150 files takes ~5 min, so give it a `--limit` or a longer `ATLAS_JOB_LEASE_SECONDS`) |

For each SEC company, in its own window:

1. Check `GET /api/v1/queue`: no pause, `codex.backfill_held` false, nothing of the previous company still `budget_held`.
2. Enqueue it with a cap below the backfill limit (20 of 28 leaves room for zero-fact reprocesses): `atlas ingest --company <slug> --backfill --max-retains 20`. The worker runs the ingest (SEC fetching isn't budgeted) and its retains within the budget.
3. Read the plan: `GET /api/v1/ingest-plans?company=<slug>`: `document_count`, `estimated_retain_operations` and the documents (forms, dates). If the estimate is far above the cap, the company needs several windows.
4. The ingest job's artifacts show `retains_deferred`. While it's above 0, in the next window run the same command again with a new key (the default, without `--key`): it fetches only what changed and retains the next 20 not-yet-retained versions, newest first. Move to the next company when `retains_deferred` is 0 and its retains have completed (`GET /api/v1/source-versions/{id}/memory`).
5. Mental-model refreshes and consolidation also spend Codex on the shared server without an operation Atlas counts; if `quota` pauses appear while `used` stays low, lower `ATLAS_CODEX_BUDGET_OPERATIONS`.

## Discovery channels: SearXNG needs the owner's attention (pilot fix 12)

**The owner's SearXNG instance returns nothing usable** (probed 2026-09-30 with the pilot query, `language` en, en-US, en-GB and all): Bing answers off topic (Swedish news, portal logins, YouTube help), Brave "too many requests", DuckDuckGo a CAPTCHA, Startpage and Qwant parsing errors, Mojeek and Presearch access denied, Google, Yahoo and Wikipedia no results. Atlas can't fix that from its side; the instance's engines need the owner: check each engine's status page in SearXNG's preferences, give Brave an API key or drop it, try Bing with the instance's region set to en-US, and consider a keyed engine. `ATLAS_SEARXNG_ENGINES` names the engines Atlas asks for.

Meanwhile discovery has a primary-source channel: **EDGAR full-text search**, on whenever `ATLAS_SEC_USER_AGENT` is set (`ATLAS_DISCOVERY_EDGAR_FTS=auto`; `off` turns it off). Each Scout or Skeptic query's `filing_phrase` is searched there, so an investigation whose SearXNG searches all fail or find nothing still gets filing leads. To see what each channel did: `GET /api/v1/discoveries/{id}`: per query, `status`, `result_count` and `unresponsive_engines` for SearXNG, and `edgar` (`q`, `status`, `total_hits`, `result_count`, `error`) for EDGAR. `GET /api/v1/leads` shows `origin` `edgar_fts` leads with their `filing` (CIK, form, date, `ingestable`). EDGAR's fair-access rules apply: the SEC User-Agent with a contact email, and at most 10 requests/s shared with the ingest (the SEC client enforces both).

## TradingView (owner override, ticket 31)

The owner's TradingView subscription is a source through TradingView's MCP server (`https://mcp.tradingview.com/mcp`). This is a private, non-commercial PoC that knowingly overrides TradingView's display-only terms (`docs/decisions.md`, "Owner override: TradingView as a source"). It is **off by default**. Scope: earnings-call and conference transcripts (Tier B Source Versions), the filing catalog (metadata) and news-headline leads (Tier C). Never prices, fundamentals, the screener, alerts or watchlists. Before real content can reach the repository, make it private. Fixtures stay synthetic.

### Getting Atlas its own token

Atlas uses its own OAuth client and token, not Claude Code's.

1. Turn it on for this shell: `export ATLAS_TRADINGVIEW_ENABLED=true` (plus the usual `ATLAS_DATABASE_URL`, `ATLAS_ACTOR` and `ATLAS_ARCHIVE_ROOT`; the login itself touches no database).
2. `uv run atlas tradingview login`. It discovers TradingView's authorization server from the MCP server's protected-resource metadata and registers a client dynamically. If the server offers no registration, pass `--client-id`. It then prints an authorization URL (PKCE S256, with a `state` and the MCP resource) on stderr.
3. Open the URL in a browser on the same machine and sign in to TradingView. The browser is redirected to `http://127.0.0.1:<port>/callback`, where the command is waiting. It gives up after `--timeout` seconds (default 300). On a remote host, fix the port (`--port 8765` or `ATLAS_TRADINGVIEW_LOGIN_PORT`) and forward it (`ssh -L 8765:127.0.0.1:8765 host`).
4. The tokens go to `ATLAS_TRADINGVIEW_TOKEN_FILE` (default `.atlas/tradingview-token.json`, mode 0600, gitignored). The file also holds the token endpoint and client ID, so refresh is automatic: before expiry, and once after a 401. A rotated refresh token is written back. stdout shows only the expiry, the client and the file path.
5. For a cluster secret instead: `atlas tradingview login --print-tokens` prints `ATLAS_TRADINGVIEW_ACCESS_TOKEN`, `_REFRESH_TOKEN`, `_TOKEN_URL` and `_CLIENT_ID` as JSON (the only command that prints a token; don't paste it into logs or tickets). Tokens given as secrets are refreshed in memory only. If TradingView rotates refresh tokens, a restarted pod then holds a spent one. Prefer a token file on a writable volume (point `ATLAS_TRADINGVIEW_TOKEN_FILE` at it).
6. Verify: `uv run atlas tradingview check --symbol NASDAQ:LITE` makes one `get_documents` call and prints counts only (documents, total, categories, transcript views), never titles or text. This call is not recorded against the budget.

A missing token, an expired token without a refresh token, or a refused refresh (`invalid_grant`) fails with a message that says to run the login again.

### Turning it on and off

- **On:** `ATLAS_TRADINGVIEW_ENABLED=true` for the worker, with the token file (or secrets) in place. Each company needs `tradingview_symbol` in `configs/themes/ai-infrastructure.yaml` (for example `NASDAQ:LITE`, `HKEX:3308`).
- **Run:** `atlas jobs enqueue tradingview_catalog --key <K> --payload '{"company": "lumentum"}'`. The catalog job lists the company's documents over `ATLAS_TRADINGVIEW_LOOKBACK_DAYS` (730) and its news headlines. If transcripts aren't yet in the ledger, it enqueues `tradingview_transcripts`, which fetches at most `ATLAS_TRADINGVIEW_MAX_CALLS_PER_JOB` (20) of them, newest first. A rerun (new key) takes the rest. English transcripts are then retained as usual.
- **Read:** `GET /api/v1/tradingview/catalog?company_id=&category=&has_transcript=` (which filings and calls exist, with the Source Version of each fetched transcript), `GET /api/v1/leads?theme=photonics` (headline leads have `origin: tradingview_news`), `GET /api/v1/queue` (the `tradingview` budget: tool calls per window, `ATLAS_TRADINGVIEW_BUDGET_REQUESTS`, default 200).
- **Off:** unset `ATLAS_TRADINGVIEW_ENABLED` (or set it `false`) and restart the worker. Queued TradingView jobs then fail without calling TradingView. Delete the token file (and revoke the client in TradingView's account settings, if it lists it) to withdraw access entirely. Stored items stay in the ledger, each marked with the override.
