# The archive-search baseline

Type: grilling
Status: open
Blocked by: none

## Question

The Codex review (2026-09-30) asked that the pilot compare each investigation with an archived-document-search baseline; nothing in the repo defines it. Decide:
- what the baseline is: a plain search of the archived parsed Source Versions of the seed companies for the question's terms, with no research role; or scoped recall alone (`POST /api/v1/memory/recall`); or both, since they answer different questions (what the pipeline adds over search; what memory adds over the archive);
- how it is run reproducibly against production, read-only, and at what cost (no MiniMax tokens if possible);
- what is compared: the passages the baseline surfaces against the card's findings and the review's "missed evidence";
- where the result is recorded in each `.scratch/pilot/results.md` section.

If it needs a script, the answer specifies it; building it is part of this ticket only if it is small (a read-only script under `scripts/`).
