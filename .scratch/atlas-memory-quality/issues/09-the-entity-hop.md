# 09: The entity hop: from a company to every document in the theme that names it

**What to build:** An investigation that reads about a company also finds what other companies' documents say about it. A question seeded with Coherent reaches AXT's 8-K because that 8-K names Coherent, whether or not a recall happened to rank it.

Spec: `.scratch/atlas-memory-quality/spec.md` ("The entity hop"). Study: finding 4 (the memory listing by `entity_id` is an exhaustive, filterable lookup). Recordings: ticket 01 (`memories/list?entity_id=`, the entities a retain with `entities` produces).

- After the Scout's recalls, for each company the pointers name (seeds first, at most `ATLAS_ENTITY_HOP_MAX_COMPANIES`, default 6), Atlas finds the company's entity in Memory (the name ticket 04 sends, exact) and lists the theme's facts that carry it, available by the as-of time, at most `ATLAS_ENTITY_HOP_MAX_FACTS` per company, newest first.
- A fact from a document of another company that resolves to a section becomes a reading pointer of kind `entity`, naming the company whose document it is and the company it was found for. Facts from the company's own documents make no entity pointer (recall already covers them).
- Entity pointers join the ranking of pointed companies with their own weight (a setting; default half a recall pointer's best weight) and passage selection as their own channel, with a share that cannot crowd out recall pointers (the ceiling rule of passage selection applies to the channel).
- No LLM call, no budget; a listing that fails is an event and the Scout goes on. A company with no entity in Memory is recorded as such.
- The investigation read shows entity pointers apart from recall pointers; the card's `read` and `not_read` name the channel.
- Co-mention stays a reason to read: no edge, no Evidence, no text to a role. `docs/decisions.md`: "The entity hop".

Migration revision `0064` (down: main's head).

**From ticket 01 (recordings `entities/`, `entity_memories/`):** names sent with `resolve_entities` false are attached to every fact of the item as written, but the extractor's own short forms are not merged into them ("Aurora" and "Aurora Optics" stay two entities). So the hop lists facts by the canonical entity Atlas sends (ticket 04), found by exact name; a fact retained before ticket 04's profile does not carry it until the backfill has re-extracted its section. The listing by `entity_id` with a tag filter is verified; its date filter is only partly verified (no fact fell outside the window), so the as-of bound is also applied in Atlas from each fact's Source Version.

**Blocked by:** 04, 07

**Status:** done

- [x] Integration test at the investigation seam: seeds A; company B's recorded filing names A in a section no recall returns; the plan gains an Investigator for B (room permitting) whose passages include that section, selected by `entity`. (B's document is a hand-shaped manual import, AXT's note, not an EDGAR filing; the selection tag is `entity_pointer:<A's id>`, since `entity:<id>` already means a name match in the search channel: `docs/decisions.md`, "The entity hop".)
- [x] A fact available after `as_of` makes no pointer; a company's own documents make none; the bounds hold.
- [x] A failed listing leaves the Scout succeeded with an event; a company without an entity is recorded.
- [x] The read and the page show the channel (frontend unit test of the pure part); API client regenerated.
- [x] Decision entry; glossary entry if a new term is needed; `AGENTS.md` line.
