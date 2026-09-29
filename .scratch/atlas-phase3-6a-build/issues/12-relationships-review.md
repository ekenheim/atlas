# 12: Relationships and review

**What to build:** Assertions with whitelisted predicates form typed, directed, layer-tagged Relationships. A separate Reviewer model plus deterministic checks (verbatim span, Tier A source, directional language) mark qualifying ones `machine_reviewed`; others go to the exceptions queue. The owner can approve or reject any Relationship; every state change is audited.

Spec: `.scratch/atlas-phase3-6a/spec.md`.

**Blocked by:** 10 (Investigator Claims → Assertions); 11 (Evidence Families)

**Status:** ready-for-agent

- [ ] Relationship schema with review state, Evidence count and family count
- [ ] Reviewer role and a directional-language checker (unit tested)
- [ ] Exceptions queue in the API; owner approve/reject endpoints, audited
- [ ] Gate test: a reviewer can establish a directed supplier/product edge and open its source span
- [ ] Metrics: Relationships by review state
