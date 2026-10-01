# 17: `skeptic-plan.v3` returns an empty plan

**What to build:** In investigation 1 on 0.2.5 (`ead2b86e-3556-42ba-9f3e-08660a938f98`), the Skeptic's plan call (role call `21b98d30-2654-44ed-8147-b98af5a1bebc`, prompt `skeptic-plan` v3, MiniMax-M3) answered `{"queries": [], "documents": []}`. Under v2 on 0.2.3 the same question got 10 queries and no documents. The fallback (fix 06) supplied four documents, so the Skeptic read; but it searched nothing of its own: no web query, no EDGAR phrase, no document chosen from the catalog.

Diagnose from the recorded request and output of that role call (`GET /api/v1/runs/a54b3ec5-3466-4038-a9be-b39cce2b636a/role-calls`): whether the prompt's wording lets "nothing" stand as an answer, whether the catalog or the Claims were sent as expected, and whether the schema allows empty lists. Then make an empty plan impossible or rare: a minimum of queries per bear-checklist item the Claims touch, and at least one catalog document when the catalog is not empty. `scripts/investigator_replay.py` shows the pattern for replaying a role's request against prompt variants.

**Blocked by:** None

**Status:** needs-triage

- [ ] The diagnosis, with the role call's request and output, in this ticket.
- [ ] A prompt or schema change measured live on the recorded request (the owner's go-ahead; a handful of chat completions), reported with the plans it produced.
