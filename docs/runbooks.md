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
