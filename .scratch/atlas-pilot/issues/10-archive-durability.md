# Archive durability: versioning, object lock and the off-cluster copy

Type: grilling
Status: open
Blocked by: none

## Question

The spec wants the `atlas-archive` bucket versioned, object-locked where possible, and "replicated off-cluster alongside the existing R2 backups". Ticket 08 found that no replication mechanism exists to reuse: R2 supports none of versioning, object lock or MinIO replication, and the other backups write their own copies to R2 directly. Decide:

- versioning and object lock on the MinIO bucket (compliance vs governance mode, retention period), given that the OpenTofu module must be extended and is applied by hand
- how the off-cluster copy is made: a scheduled `mc mirror` / rclone CronJob to R2, Atlas writing a second copy itself, or no off-cluster copy for the pilot
- what immutability guarantee the R2 side offers, given it has no object lock
- whether published Research Snapshots (content-addressed JSON) need anything stronger than Source Versions

## Facts so far (2026-09-28)

- MinIO runs in the `storage` namespace (app-template 5.2.1, image `RELEASE.2025-09-07T16-13-09Z`), with its S3 API at `s3.<domain>` and data on the PVC `minio-data`. Source: the wiki's storage-and-backups page and `kubernetes/apps/storage/minio/`.
- **To verify:** whether this single-node deployment's on-disk format supports bucket versioning and object lock. Single-drive erasure mode does; legacy FS mode does not. A one-off `mc version info` / `mc retention` probe answers it.
- OpenTofu: the `terraform/minio` module exists, but no OpenTofu custom resources exist, and the owner says tofu-controller isn't running (it could be turned on). So the bucket's creation path is part of this decision:
  - (a) enable tofu-controller and add an OpenTofu CR for `terraform/minio`
  - (b) apply `terraform/minio` by hand (the state location must then be settled)
  - (c) create the bucket and its user with `mc`, outside the OpenTofu convention
