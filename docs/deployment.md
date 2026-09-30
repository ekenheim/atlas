# Deployment

Atlas ships as one container image, `ghcr.io/ekenheim/atlas`. It runs as `atlas api` (the default command) or `atlas worker`, and `atlas migrate` applies the schema. The cluster side (home-ops, `kubernetes/apps/datasci/atlas/`) is covered by spec Part B: Deployment.

## Releases

A release is a git tag `vX.Y.Z` on `main`. Pushing the tag runs `.github/workflows/release.yml`:

1. **`ci` job:** `scripts/ci.sh --no-image`, the same gates as every CI run (ruff, strict pyright, frontend lint/typecheck/export, pytest against Postgres and Silo).
2. **`publish` job** (only if `ci` passed):
   - builds the multi-stage `Dockerfile` for `linux/amd64` only, since the cluster has no other architecture
   - runs `scripts/image-smoke.sh` on the image (non-root, read-only root filesystem, writable `/tmp`, liveness and frontend served)
   - pushes to GHCR only after the smoke passes

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

Then watch the run under **Actions → release**. The `ci` job runs on the owner's self-hosted scale set (since 0.2.3; GitHub's hosted runners took over 30 minutes for the suite), the `publish` job on GitHub's. A failed `ci` job publishes nothing. To retry, fix `main`, then tag a new patch version; don't move or re-push an existing tag.

### First release: make the package public (once)

GHCR creates a new package as **private**, even when the repo is public. After the first successful release, go to github.com/ekenheim → **Packages** → `atlas` → **Package settings** → **Change visibility**, and set it to **Public**. This is needed once, never again. Until then, the cluster (which has no `ghcr-pull` secret, per spec) and Renovate can't pull the image.

In the same settings page, check that **Manage Actions access** lists `ekenheim/atlas` with write access. The first push from the workflow normally sets this up.

### Deploying a release

Renovate in home-ops sees the new `X.Y.Z` tag and opens a bump PR. Automerge is off for Atlas, so the owner merges the PR to deploy (spec Part B: Releases).
