# Research Snapshots and the replay leakage test (Phase 6a)

Type: grilling
Status: resolved
Blocked by: none

## Question

Decide:
- snapshot contents (§5.7) and storage (archive, content-addressed JSON; lock semantics on the PVC vs S3)
- what 'cannot be altered' means and how it's tested
- the minimal replay bank: how it's seeded without leakage (the export/import question parked from Phase 2), and the future-dated fixture
- replay cost and budget on the shared Hindsight

## Answer

Grilled 2026-09-29; the owner accepted all.

- **Snapshots:** a content-addressed JSON object in the archive (`snapshots/<sha256>`) plus an insert-only `research_snapshot` row (trigger-enforced, like the audit trail); the hash is verified on read. On the filesystem archive, immutability is enforced by the app and database, not the storage (a known limitation until MinIO object lock).
- **Replay:** the bank `atlas-replay-<id>` lives on the **local** Hindsight, never the shared server. It's seeded by re-retaining only Source Versions with `available_at ≤ cutoff` (not export/import, which could carry post-cutoff extraction). A synthetic future-dated fixture must be accepted 0 times. ~3 documents, to bound cost.
