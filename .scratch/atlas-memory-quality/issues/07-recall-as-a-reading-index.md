# 07: Recall asked like a reading index

**What to build:** An investigation's pointer recalls return more distinct sections, spend no place on the same fact twice, judge recency from the investigation's as-of time, and bring an observation's sources in the same answer. Each reading pointer keeps how strongly Memory ranked it and which entities its memory names.

Spec: `.scratch/atlas-memory-quality/spec.md` ("Recall as a reading index"). Study: finding 3. Recordings: ticket 01 (recall's `max_tokens`, `types`, `prefer_observations`, `include.source_facts`, `query_timestamp`, `scores`, the entities map).

- The gateway's recall takes `max_tokens`, `types`, `prefer_observations`, `query_timestamp` and the include options, and its result keeps each memory's scores, entity names and IDs, chunk ID and, for an observation, its source facts from the same answer.
- The provenance resolver uses the source facts of the answer; it asks Hindsight for a memory only when a source is missing from it (the answer's truncation flag).
- Pointer recalls (the Scout's and the Skeptic's) use `ATLAS_POINTER_RECALL_MAX_TOKENS` (default 8192), `budget` high, `prefer_observations`, and `query_timestamp` equal to the investigation's as-of time. Replay questions send the replay's cutoff.
- `POST /api/v1/memory/recall` accepts the new fields (all optional, today's behaviour when absent) and returns scores and entities per memory.
- A reading pointer stores the final score and the entity names (insert-only as before). The investigation read and the Research Snapshot carry them. Pointed companies are ranked as today; nothing weights by score yet.
- `docs/decisions.md`: "Recall as a reading index" (each field, why, and that the score is recorded before it is used).

Migration revision `0063` (down: main's head).

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] Integration test at the investigation seam: the Scout's recalls are sent with the setting's `max_tokens`, `budget` high, `prefer_observations` and the as-of time as `query_timestamp`; the pointers carry score and entities; the read returns them.
- [ ] An observation in a recall resolves to its sections without a per-memory request when its sources are in the answer, and with one when the answer was truncated (the fake counts requests).
- [ ] The public recall with no new field behaves as before (existing tests unchanged); with them, the request and the answer carry them.
- [ ] The pointer table still refuses UPDATE and DELETE; the snapshot test covers the new fields.
- [ ] API client regenerated; decision entry; `AGENTS.md` line.
