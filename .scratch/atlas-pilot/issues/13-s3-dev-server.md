# S3-compatible server for dev/CI archive contract tests

Type: research
Status: resolved
Blocked by: none

## Question

MinIO no longer publishes pullable images or binaries (ticket 10). Which S3-compatible server should Atlas's Compose and CI use, so the archive contract suite exercises the same semantics as the cluster MinIO? Required:

- the S3 API used by the archive: put/get/head, conditional put, and listing
- **bucket versioning** and **object lock** (Governance retention; a delete or overwrite denied without bypass)
- a pullable, maintained image from ghcr.io, Docker Hub or quay without auth
- starts in seconds with an acceptable licence
- behavior that is close enough to MinIO that contract tests transfer

Candidates: SeaweedFS, LocalStack S3, moto server mode, Garage, RustFS, Versity S3 Gateway, and any maintained community MinIO build. For each: image, licence, versioning, object lock (Governance/Compliance, retention and bypass header), known MinIO incompatibilities. Recommend one, with a fallback.

## Context

Research in progress on branch `research/s3-dev-server`; findings in `docs/research/s3-dev-server.md` on that branch.

## Answer

Full findings: `docs/research/s3-dev-server.md` on branch `research/s3-dev-server` (`1cc4e15`).

- **MinIO:** confirmed shut down. `dl.min.io` returns 410 ("archived"), quay has no manifest, Docker Hub denies pulls, and the GitHub repo was archived on 2026-04-25.
- **Use:** PGSTY Silo, a maintained community MinIO fork: `docker.io/pgsty/silo:RELEASE.2026-09-16T00-00-00Z@sha256:635197cb9f36d01bee221d34d1c7d7960f6a95c48b0b6c01d99cd13bdae51a46`. It is AGPL, single-vendor, renamed in August, and newer than the cluster build.
- **Fallback:** RustFS, `rustfs/rustfs:1.0.0@sha256:8cc9801755448b71a786705ce76692c77e14936cccd87cf2fc31842e58f4d1ff` (Apache-2.0).
- **Rejected:** Garage (no versioning or lock), LocalStack (needs an auth token), moto (no IAM checks), Versity (versioning experimental).
- **Empirical (boto3):**
  - Silo, RustFS and SeaweedFS each passed 22/22 root checks and 4/4 checks as a scoped user without bypass rights.
  - Covered: lock bucket, Governance default retention, `If-None-Match` → 412, permanent version delete refused without bypass and allowed with it, legal hold, Compliance.
  - Silo was ready in 0.26 s. minio-py itself was not tested.
- **Correction to the ticket's premise:** on AWS, MinIO and all candidates, an overwrite creates a **new version** and a plain delete adds a delete marker. Only permanent version deletion or overwrite is refused. The contract tests must assert that.
- **Error codes differ by server:** Silo returns `400 InvalidRequest` like the cluster; RustFS and SeaweedFS return `403`/`409`. The contract tests must assert behavior, not exact codes.
