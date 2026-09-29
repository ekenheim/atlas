# 14: Investigation orchestration

**What to build:** An investigation starts from a theme question and runs a fixed, visible plan on the job queue: Scout → Investigator → Editor (Skeptic and Analyst join later). Per-run budgets (≤2 rounds, ≤10 leads, ≤25 fetched documents, a token ceiling) apply; every stop records its reason; an LLM outage pauses and resumes; a disproven premise cancels only its dependent tasks.

Spec: `.scratch/atlas-phase3-6a/spec.md`.

**Blocked by:** 08 (Scout and leads); 10 (Investigator Claims → Assertions)

**Status:** done

- [x] Run and task model (task rows per role) extending the minimal run
- [x] `POST investigations`, `GET investigations/{id}`, `GET investigations/{id}/events`
- [x] Stop reasons `answered | no_new_independent_evidence | budget_exhausted | needs_review | premise_disproven` recorded
- [x] Gate test: budget exhaustion and an LLM outage produce a resumable partial investigation; no invented text
- [x] Metrics: investigation stops by reason
