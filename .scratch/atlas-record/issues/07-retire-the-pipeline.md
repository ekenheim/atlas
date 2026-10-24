# Retire the pipeline

Type: task
Status: wontfix
Blocked by: 00, 03, and two Mondays of editions imported and checked on production

## What

1. **Back up first.** Back up the Postgres database and the archive bucket, then restore the backup once into a throwaway database to prove it works.
2. **Write the ADR.** Add `docs/adr/0005-...`, recording what is deleted and how to get it back: the tag before the deletion.
3. **Delete, in one release:**
   - investigations and their roles;
   - Claims, Relationships and their review;
   - triage, retention, consolidation and mental models;
   - replay and evaluation;
   - the Scout, Researcher, Skeptic, Scorecard and Watch agents, and their prompts;
   - the MiniMax and Codex budgets that only these used.

   A migration drops their tables, and only after the backup. The audit chain keeps their events.
4. **Clean up home-ops.** A PR removes the suspended CronJobs and the settings they used. The owner merges it.
5. **Shrink AGENTS.md** to what remains.

## Done when

- [ ] The release is live, CI is green, and the record pages still render every edition.

## Comments

- 2026-10-24, lead: superseded by ADR 0005. Atlas is archived rather than deleted, so no backup and no deletion are needed.
