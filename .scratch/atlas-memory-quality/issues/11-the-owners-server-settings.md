# 11: The owner's server settings

**What to build:** The owner gets one home-ops pull request with the Hindsight server settings the study and ticket 15 recommend, each with what it changes for Atlas and for the server's other consumers, so that the decision is the owner's with the facts in front of them.

Spec: `.scratch/atlas-memory-quality/spec.md` ("The owner's server settings"). Study: finding 7 (observed in `kubernetes/apps/llm/hindsight/app/helmrelease.yaml`). Ticket 15 decides the embedding model and measures the thresholds; this ticket carries its result.

This is the lead's ticket (the `release-atlas` skill's home-ops steps); the owner merges.

- Always in the PR: `HINDSIGHT_API_FAIL_ON_EXTRACTION_ERRORS=true` (a retain with lost chunks ends failed, which Atlas retries after ticket 03; other consumers see failures they did not see before), and a reranker chain that ends in rank fusion (a reranker outage degrades the order instead of failing every recall).
- From ticket 15: either the query instruction for the current embedding model as `HINDSIGHT_API_EMBEDDINGS_QUERY_PREFIX` (query side only, nothing re-embedded; the manifest's comment that the client cannot add one is corrected), or the embedding model change the owner approves, with its migration written out.
- Proposed with their measurement, each in its own commit so the owner can drop it: the similarity thresholds ticket 15 recommends; a consolidation model of its own if ticket 01's cost per section makes consolidation the constraint.
- The PR body states, per setting: the docs' wording, the default, the effect on every bank of the shared server, and how to check it after the merge (the probe set and the conformance check).

**Blocked by:** 02, 15

**Status:** ready-for-human

- [ ] The PR is open with its checks reported; each setting has its reasoning and its check.
- [ ] After the owner's merge: the probe set and the conformance check are run again and the difference is in the implementation log.
