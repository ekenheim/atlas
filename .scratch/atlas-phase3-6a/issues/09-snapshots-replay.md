# Research Snapshots and the replay leakage test (Phase 6a)

Type: grilling
Status: open
Blocked by: none

## Question

Decide:
- snapshot contents (§5.7) and storage (archive, content-addressed JSON; lock semantics on the PVC vs S3)
- what 'cannot be altered' means and how it's tested
- the minimal replay bank: how it's seeded without leakage (the export/import question parked from Phase 2), and the future-dated fixture
- replay cost and budget on the shared Hindsight
