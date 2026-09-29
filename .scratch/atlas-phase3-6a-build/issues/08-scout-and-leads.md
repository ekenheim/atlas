# 08: Scout and leads

**What to build:** The Scout turns a theme question plus the Bottlenecks mental model's open gaps into at most 10 SearXNG queries (engines named explicitly, `format=json`). Results become Tier C leads (URL, title, snippet, query, engines, date), deduplicated by canonical URL, and are never Evidence nor retained into Hindsight.

Spec: `.scratch/atlas-phase3-6a/spec.md`.

**Blocked by:** 07 (Role-call foundation)

**Status:** done

- [x] A SearXNG client recording `unresponsive_engines`, tested from recorded responses (hand-written in SearXNG's documented JSON shape, not recorded live; see the implementation log)
- [x] A `lead` table and `GET /api/v1/leads`
- [x] A discovery job runs the Scout and stores leads; a rerun deduplicates
- [x] A test proves leads never create retain jobs or Evidence
- [x] Metrics: discovery queries and leads
