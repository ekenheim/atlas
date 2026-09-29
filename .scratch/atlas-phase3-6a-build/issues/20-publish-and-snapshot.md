# 20: Publish gate and Research Snapshot

**What to build:** Publishing a Hypothesis version requires ≥1 falsifier, ≥1 unresolved question and owner approval of the Relationships it depends on, and freezes a Research Snapshot (§5.7): content-addressed canonical JSON in the archive plus an insert-only `research_snapshot` row, verified by hash on every read.

Spec: `.scratch/atlas-phase3-6a/spec.md`.

**Blocked by:** 12 (Relationships and review); 16 (Hypotheses); 19 (Scenarios and Financial Analyst)

**Status:** ready-for-agent

- [ ] Publish endpoint enforcing the gate with typed errors
- [ ] Snapshot contents per §5.7 (cutoff, Source Versions, Memory text as returned, Assertions, financial dataset hash, prompts and model versions, Hindsight version, outputs)
- [ ] Insert-only trigger; the audit event references the hash; `GET snapshots/{id}` verifies it
- [ ] Gate test: a published snapshot can't be altered (DB and hash)
- [ ] Metrics: snapshots
