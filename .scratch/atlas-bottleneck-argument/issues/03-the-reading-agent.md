# 03: The reading agent

**Status:** done (implementer; the Reader runs standalone as the `read_step` job; inside an investigation it is ticket 05's argument plan)
**Type:** task
**Blocked by:** 01, 02

**What to build:** a research role, the **Reader**, that works one argument step of one question the way the researcher's hour did: it chooses what to search, reads what it chooses, and records Facts (ticket 02). It runs as a loop of role calls (the existing `atlas.roles` caller: versioned prompt, strict JSON schema, one repair then quarantine, the run's token budget), each answering with one action:

- `search_archive {query, company_slugs}`: ticket 01's term search over those companies (the seeds and any universe company), as of the investigation's as-of time; the hits (title, kind, date, the passage text, a hit id) come back in the next call;
- `recall {query}`: Memory recall scoped to the theme, at budget high and 16,000 tokens, each memory with its resolved source section;
- `read {hit_id or source_version_id + anchor}`: the passage, or the section's text in windows;
- `record_fact {source_version_id, quote, company_slug, step, statement, quantity?, period?, status}`: the quote is located in the parse (exact or its one folded occurrence, as Claims are placed) and recorded as a Fact; a refusal comes back with its reason so the agent can correct it;
- `done {summary}`.

Bounds per step: `ATLAS_READER_MAX_CALLS` (default 12) calls, `ATLAS_READER_MAX_PASSAGES` (40) passages read; the investigation's token budget over all. Steps run in parallel (one Reader per step), so latency is the slowest step, not the sum.

The prompt says what a researcher looks for at each step (from `docs/research/serenity-skills-alignment.md` on its branch and the spec's steps), to prefer the companies' own words in calls and filings, to record magnitudes, dates and status exactly as quoted, and never to turn a plan, a development, a hedge or an agreement into present fact (the verdict's misstatements, pilot fixes 34 and 35).

**Acceptance:**
- [x] `atlas.roles.reader` and its prompt `reader.v1.md`; actions validated; every call and its tokens recorded on the run.
- [x] A Reader's Facts, its searches and reads recorded on its task's artifacts (what was searched, read, recorded and refused).
- [x] Tests: the scripted LiteLLM fake drives a Reader through search, read, record (accepted and refused) and done, on the fixture filings; the bounds stop it; a refused fact comes back with its reason.
