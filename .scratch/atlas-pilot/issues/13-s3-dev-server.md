# S3-compatible server for dev/CI archive contract tests

Type: research
Status: claimed
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
