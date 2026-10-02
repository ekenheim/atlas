# 13: A layer's question is also asked of that layer's facts

**What to build:** When the Scout's query concerns a supply-chain layer, Memory is also asked within the facts labelled with that layer, so a question about substrates is pointed at substrate facts across the theme even when their wording differs from the query's.

Spec: `.scratch/atlas-memory-quality/spec.md` ("Layer-aware recall"). Depends on the label tags of ticket 05 existing on stored facts, which the backfill (ticket 12) brings.

- A Scout query that carries a layer makes a second recall with the theme's scope and the layer's label tag (a compound tag filter: the theme and the label). Both recalls' pointers are kept; each pointer names the scope it came from. A memory both recalls return makes one pointer per recall as today (the pointer weight rule is unchanged and stated).
- When no fact carries the label yet, the second recall returns nothing and is recorded as such, not as a failure.
- The gateway takes compound tag filters for this one use; the public recall endpoint accepts a `layer` in its scope.
- The Scout task's artifacts count layer recalls and their pointers; the investigation page shows the scope of each pointer.
- `docs/decisions.md`: "Layer-aware pointer recall".

**Blocked by:** 05, 07, 12

**Status:** done

- [x] Integration test at the investigation seam: a layer-tagged Scout query produces two recalls; a fact labelled with the layer and worded unlike the query is pointed at through the second; an unlabelled bank gives none and no failure.
- [x] The public recall with a `layer` scope filters (API test); the API client is regenerated.
- [x] Decision entry; `AGENTS.md` line.

**Notes (implementer):** The Scout's queries carried no layer, so `scout.v5` asks for one per query (`discovery_query.layer`, migration `0073`), kept only when it names a layer of the taxonomy; see `docs/decisions.md`, "Layer-aware pointer recall". The compound filter is tested against the recorded fake's derivation of `tag_groups`, not recorded from a real Hindsight.
