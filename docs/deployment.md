# Deployment

Atlas ships as one container image, `ghcr.io/ekenheim/atlas`. It runs as `atlas api` (the default command) or `atlas worker`, and `atlas migrate` applies the schema. The cluster side (home-ops, `kubernetes/apps/datasci/atlas/`) is covered by spec Part B: Deployment.

## CI

`.github/workflows/ci.yml` runs on every push to any branch of this repo (never on fork pull requests: the suite uses the owner's runners). It has four jobs:

| Job | Runs on | What |
|---|---|---|
| `changes` | GitHub's runners | Whether the push needs testing. Not when a `suite` already passed on this very commit, the usual case when `main` is fast-forwarded to a green `integrate/` branch: check runs belong to the commit, so it was tested once and that is enough (2026-10-08; it used to run the whole suite again). Not when it changed no code: nothing outside `.scratch/` (the pilot plan counts, a test reads it) and `docs/implementation-log.md`. Otherwise `static` and `suite` run. |
| `static` | GitHub's runners | actionlint, then `scripts/ci.sh static`: ruff, strict pyright, frontend lint, typecheck and unit tests, the API client is current. No Docker; a few minutes. |
| `suite` | `gha-runner-scale-set-atlas` (self-hosted, dind) | Only after `static` passes: `scripts/ci.sh suite`: Compose services, pytest (8 workers), the Playwright e2e tests, the image build and smoke. About 15 minutes. |
| `ci` | GitHub's runners | Green when both passed, or when the push changed no code. **The check `main` requires**, so every push gets one. |

`scripts/ci.sh` with no argument runs both stages, so a laptop runs what CI runs.

**Capacity.** The scale set (home-ops, `kubernetes/apps/actions-runner-system/gha-runner-scale-set-atlas`) runs at most 3 runners, each requesting 4 CPUs and 8 GiB. Jobs beyond that wait in GitHub's queue, where the job timeout doesn't run. Before this cap, 10 unrequested runners starved each other: on 6 October, 13 Renovate branches pushed at once and 9 runs passed the 60-minute timeout. Renovate is held to 3 branches at once for the same reason.

**Main is gated.** A repository ruleset on `main` requires the `ci` check and forbids force-pushes and deletion. The check belongs to the commit, so fast-forwarding `main` to a green integration branch passes; a commit without a green `ci` run can't land on `main`.

**Dependencies.** Renovate (`renovate.json`, extending the owner's shared preset) opens update PRs. npm minor and patch updates and the weekly lock-file refresh merge themselves once `ci` is green. Majors, the runtime Python, the test Postgres (it follows production's) and Hindsight (pinned to the spiked, recorded version) wait for a person. Actions are pinned by commit, with the version in a comment; Renovate updates both.

**Flaky tests are bugs.** A test that fails and then passes on a rerun is fixed or its expectation corrected, not retried; record the cause in the commit.

## Releases

A release is a git tag `vX.Y.Z` on `main`. Pushing the tag runs `.github/workflows/release.yml`:

1. **`verified` job:** whether a `suite` job already passed on the tagged commit (a green `ci` that skipped its stages tested nothing, so it doesn't count).
2. **`ci` job** (only if it had not): `scripts/ci.sh --no-image`, the same gates as every CI run (ruff, strict pyright, frontend lint/typecheck/export, pytest against Postgres and Silo).
3. **`publish` job** (only if the commit passed CI, there or here):
   - builds the multi-stage `Dockerfile` for `linux/amd64` only, since the cluster has no other architecture
   - runs `scripts/image-smoke.sh` on the image (non-root, read-only root filesystem, writable `/tmp`, liveness and frontend served)
   - pushes to GHCR only after the smoke passes
   - attaches an SBOM and BuildKit provenance to the pushed image, and a signed build-provenance attestation (Sigstore, stored with the repo): `gh attestation verify oci://ghcr.io/ekenheim/atlas:X.Y.Z -R ekenheim/atlas` proves the image was built by this workflow from the tagged commit

The job uses the workflow's `GITHUB_TOKEN` with `packages: write`. No other secrets are needed.

Tags pushed for `v1.2.3` at commit `abc…`:

| Tag | Example | Use |
|---|---|---|
| full semver, no leading `v` | `1.2.3` | What Renovate tracks and what home-ops pins |
| commit SHA | `sha-<40-hex commit>` | Trace an image back to its commit |

No `latest` tag is published, so a deploy always names a version.

The image carries these OCI labels:

- `org.opencontainers.image.source=https://github.com/ekenheim/atlas`
- `org.opencontainers.image.version` (for example `1.2.3`)
- `org.opencontainers.image.revision` (the commit SHA)

The `source` label links the GHCR package to this repo.

The workflow also passes two build args, which become the image's environment:

- `ATLAS_VERSION`: the tag's version, reported by the `atlas_build_info` metric. The release smoke fails if the metric reports anything else.
- `ATLAS_CODE_VERSION`: the commit SHA, recorded on every run.

`pyproject.toml`'s version (`atlas.__version__`) is only the fallback, for local builds.

### Cutting a release

```bash
git switch main && git pull
scripts/ci.sh                      # optional: full local run, including image build + smoke
git tag -a v1.2.3 -m "Atlas 1.2.3"
git push origin v1.2.3             # triggers the release workflow
```

Then watch the run under **Actions → release**. Its `verified` job asks GitHub whether `ci.yml` already passed on the tagged commit (on any branch: normally the integration branch the release was cut from). If it did, the suite is not run again and `publish` follows at once (since 0.4.4; it took 32 minutes). If not, the `ci` job runs the suite on the owner's self-hosted scale set (since 0.2.3; GitHub's hosted runners took over 30 minutes for the suite). The `publish` job runs on GitHub's runners. A failed `ci` or `verified` job publishes nothing. Pushes that change only `.scratch/` (the tracker, except the pilot plan a test reads) or `docs/implementation-log.md` get a green `ci` without the suite, so a release of such a commit runs the suite itself. To retry, fix `main`, then tag a new patch version; don't move or re-push an existing tag.

### First release: make the package public (once)

GHCR creates a new package as **private**, even when the repo is public. After the first successful release, go to github.com/ekenheim → **Packages** → `atlas` → **Package settings** → **Change visibility**, and set it to **Public**. This is needed once, never again. Until then, the cluster (which has no `ghcr-pull` secret, per spec) and Renovate can't pull the image.

In the same settings page, check that **Manage Actions access** lists `ekenheim/atlas` with write access. The first push from the workflow normally sets this up.

### Deploying a release

Renovate in home-ops sees the new `X.Y.Z` tag and opens a bump PR. Automerge is off for Atlas, so the owner merges the PR to deploy (spec Part B: Releases).

### The worker's lease

The worker renews its job's lease while the job runs (`docs/runbooks.md`, "The worker's lease"), so `ATLAS_JOB_LEASE_SECONDS` only sets how soon a crashed worker's job is reclaimed. The home-ops override `ATLAS_JOB_LEASE_SECONDS=1800` can be removed once the release containing the heartbeat is deployed; the default of 300 s then reclaims a crashed worker's job within 5 minutes.
