# 09: Candidates

**What to build:** A lead naming a company outside the universe is resolved and proposed as a Candidate (§8.3 states). The owner commits it (the company joins the universe in the database and its ingest is enqueued) or rejects it with a reason; rejected Candidates are kept.

Spec: `.scratch/atlas-phase3-6a/spec.md`.

**Blocked by:** 02 (Entity resolution and identity review); 08 (Scout and leads)

**Status:** ready-for-agent

- [ ] Entity mentions in leads go through entity resolution; unseeded matches create Candidates, linked to their leads
- [ ] `GET candidates`, `POST candidates/{id}/commit`, `POST candidates/{id}/reject` (audited)
- [ ] Gate test: an unseeded company is discovered from a SearXNG fixture and becomes a Candidate
- [ ] Committing enqueues the right ingest for its source path; Candidates are never deleted
- [ ] Metrics: Candidates by state
