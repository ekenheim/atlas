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

Also note where the OpenTofu state lives, since it isn't in the repo; that is a question for the owner.
