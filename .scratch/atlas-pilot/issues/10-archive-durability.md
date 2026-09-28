# Archive durability: versioning, object lock and the off-cluster copy

Type: grilling
Status: resolved
Blocked by: none

## Question

The spec wants the `atlas-archive` bucket versioned, object-locked where possible, and "replicated off-cluster alongside the existing R2 backups". Ticket 08 found that no replication mechanism exists to reuse: R2 supports none of versioning, object lock or MinIO replication, and the other backups write their own copies to R2 directly. Decide:

- versioning and object lock on the MinIO bucket (compliance vs governance mode, retention period), given that the OpenTofu module must be extended and is applied by hand
- how the off-cluster copy is made: a scheduled `mc mirror` / rclone CronJob to R2, Atlas writing a second copy itself, or no off-cluster copy for the pilot
- what immutability guarantee the R2 side offers, given it has no object lock
- whether published Research Snapshots (content-addressed JSON) need anything stronger than Source Versions

## Facts so far (2026-09-28)

- **Read-only probe** (S3 API, as a non-admin user):
  - 17 buckets exist; **none** has versioning or object lock.
  - The OpenTofu module lists only `longhorn`/`postgresql`/`volsync`, and `longhorn` doesn't exist. So in practice buckets are made by hand.
  - Admin info returned 403, so the drive mode wasn't read directly. Inference: `RELEASE.2025-09-07` can't run on the legacy FS format, so versioning and object lock should be supported. Creating the bucket with object lock proves it.
- **MinIO images are no longer publicly pullable:** `quay.io/minio/minio` (including the cluster's pinned tag), Docker Hub `minio/minio`, `minio/mc`, and `dl.min.io` binaries (410).
  - Local dev/CI can't use MinIO in Compose.
  - The cluster's MinIO depends on the node's image cache (a home-ops risk, flagged to the owner).

- MinIO runs in the `storage` namespace (app-template 5.2.1, image `RELEASE.2025-09-07T16-13-09Z`), with its S3 API at `s3.<domain>` and data on the PVC `minio-data`. Source: the wiki's storage-and-backups page and `kubernetes/apps/storage/minio/`.
- **To verify:** whether this single-node deployment's on-disk format supports bucket versioning and object lock. Single-drive erasure mode does; legacy FS mode does not. A one-off `mc version info` / `mc retention` probe answers it.
- OpenTofu: the `terraform/minio` module exists, but no OpenTofu custom resources exist, and the owner says tofu-controller isn't running (it could be turned on). So the bucket's creation path is part of this decision:
  - (a) enable tofu-controller and add an OpenTofu CR for `terraform/minio`
  - (b) apply `terraform/minio` by hand (the state location must then be settled)
  - (c) create the bucket and its user with `mc`, outside the OpenTofu convention

## Answer

Grilled 2026-09-28; Q15–Q19 accepted as recommended.

15. **Creation:** a re-runnable provisioning script in the Atlas repo, using the `minio` Python package (`Minio` + `MinioAdmin`). It creates `atlas-archive` with object lock enabled, a dedicated `atlas` user, and a policy scoped to that bucket, and prints the credentials for Bitwarden. The owner runs it once with root credentials. This deviates from the "managed by OpenTofu" convention; see `docs/decisions.md`.
16. **Lock:** default retention in **Governance** mode for **10 years**. The `atlas` user has no `s3:BypassGovernanceRetention`, while root keeps the escape hatch. Versioning is implied.
17. **Off-cluster copy:** a nightly CronJob copies (never deletes) `atlas-archive` to the R2 bucket `atlas-archive-offsite`. R2 has no object lock, so it is a backup copy, not the immutability guarantee. The R2 cost at pilot size is to be confirmed (flag if it leaves the free tier).
18. **Snapshots:** the same bucket and policy, under the content-addressed prefix `snapshots/`.
19. **Dev/CI:** the filesystem archive backend for dev. The S3 contract suite runs against a pullable S3-compatible server that supports versioning and object lock, to be chosen by ticket 13. The spec's "MinIO in Compose" is amended.
20. **MinIO image risk:** the owner keeps MinIO as is. Mitigation already in place: Spegel (`kube-system/spegel`) mirrors cached images peer-to-peer between nodes, so a rescheduled pod can pull from another node's cache. The residual risk (every node losing its cache) is accepted.
