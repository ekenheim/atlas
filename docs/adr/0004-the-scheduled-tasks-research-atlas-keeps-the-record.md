# The scheduled tasks research; Atlas keeps the record

The research changes hands again. Under ADR 0003, a research session using Atlas's tools did the research, and Atlas's own agents (the Scout, the Researcher, the Skeptic and the Chokepoint Watch) ran in the cluster.

From 2026-10-20, the owner's claude.ai scheduled tasks research on the open web: seven theme tasks and a council. Each publishes an artifact with a machine-readable ledger. Atlas stops researching. It keeps each edition unchanged, finds rewrites, checks each quote against its source, and settles the predictions. The spec is `.scratch/atlas-record/spec.md`.

## Context

- **The bake-offs.** Three bake-offs on 2026-10-19 (robotics, power equipment, aerospace and defence; `.scratch/bakeoff/`) compared an open Claude session with the Watch on the same themes.
  - The session read several times as many primary documents (15 to the Watch's 3 in aerospace).
  - It named the chokepoints the Watch missed.
  - Its quotes were verbatim: 56 of 57.
- **The council.** The council's first two editions quoted 13 sources, and the lead found all 13 in their sources, one differing only by a comma.
- **The cause.** The Watch's limit was reach: finding and reading sources. Its gated fetch and the site register cannot keep pace with a session that searches and reads freely.
- **What the tasks cannot do.** A scheduled task cannot keep its own history. It republishes its artifact in place, it can rewrite what it said last week, and nothing checks its quotes after the fact.

## Decision

- **The tasks research.** The seven theme tasks and the council are the research. Atlas does not research, rank or write theses.
- **Atlas keeps the record:**
  - Every edition is stored insert-only.
  - Each edition is compared with the one before it.
  - Each quote is located in its archived source and tiered by who published the source.
  - Each prediction is recorded once and settled from later editions.
- **The drop box.** The ledgers reach Atlas through a private GitHub repository. A collector task writes to it through its connector, and Atlas reads from it outbound. Atlas stays LAN-only.
- **Retired:**
  - the pipeline's agents and roles;
  - Memory's retention and consolidation;
  - the scorecard.

  They are frozen by configuration first, then deleted after two Mondays on the new path and a proven backup (a later ADR).
- **The scorecard's replacement.** The scorecard needed as-of research, which a scheduled task cannot do. Dated predictions that cannot be rewritten, settled against what happened, replace it as the measure of progress.

## Consequences

- **What stays:** the source ledger, the archive, the fetch gate, parsing, the audit chain, calls and their settlement, and the pages' shell. The Belief layer stays in place until the deletion ADR decides its fate.
- **What the record cannot vouch for.** A quote verified against a third-party transcript is verified against that transcript, not against the company's own words. The tier is shown beside every result.
- **What the record cannot see.** It only holds what the tasks published. A chokepoint they never looked at is invisible to it. The council's "early candidate" slot and the owner's own reading are the remedy.
- **Reversing this.** The pipeline's code is kept at the last tag before the deletion, and its data is in the backup.
