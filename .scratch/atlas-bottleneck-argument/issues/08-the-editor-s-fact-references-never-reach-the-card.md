# 08: The Editor's Fact references never reach the card

**Status:** ready-for-agent
**Type:** bug

**What happened:** pilot question 3 on 0.5.3, argument plan (investigation `a5a7402d-…`, 2026-10-07): the statement demand_vs_supply 1 names its speaker "c1", the short reference the Editor cites Facts by, where it should say Coherent. The grounding check and the finding judge both passed it; the content is otherwise right.

**What to build:** a deterministic check on each argument statement (and each finding in the old plan) for the Editor's reference pattern (`c<digits>`, `f<digits>`, whatever `atlas.roles.editor` hands the model) as a word in the text. A statement holding one is asked again once with the reason; if it still holds one, the reference is replaced with the cited Fact's company display name when the statement cites exactly one Fact with that reference, else the statement is dropped with the reason `internal_reference`.

**Acceptance:**
- [ ] A unit test: "c1 says its data center grew 4%" with c1 → Coherent's Fact becomes "Coherent says …"; a statement naming a reference it doesn't cite is dropped `internal_reference`.
- [ ] Words that merely look like one ("C3 band", "F1 score") in the cited quote are left alone (the check looks only for references the Editor was given).
