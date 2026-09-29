# The Phase 4 research workflow

Type: grilling
Status: resolved
Blocked by: 05, 06

## Question

Decide:
- the deterministic DAG on the job table
- each role's contract (§7.2) and budget
- stop states and cancellation
- independent counterevidence (the Skeptic plus ticket 12's bear checklist, including dilution/financing)
- Hypothesis lifecycle and versioning
- the dossier export (JSON/Markdown)
- how 'no unsupported claims are promoted' is enforced

## Answer

Grilled 2026-09-29; the owner accepted all.

- **DAG** on the existing job queue: Scout → Investigator → (Skeptic ∥ Financial Analyst) → Editor. At most 2 rounds, 10 leads, 25 fetched documents, and a per-run token budget (spec §7.4), backstopped by the `atlas` LiteLLM key budget.
- **Stop states:** answered, no new independent evidence, budget exhausted, or needs human review; each stop records its reason. A disproven premise cancels only its dependent follow-ups. LLM quota or outage pauses the queue and the investigation resumes; nothing is invented.
- **Skeptic independence:** a separate counterevidence search. Neither the Investigator's output nor Hindsight Memory counts as a witness. It works from ticket 12's bear checklist (substitutes, second sources, capacity additions, inventory cycle, dilution/financing, customer concentration).
- **Hypothesis:** the §5.6 lifecycle; a published version is immutable and a correction is a new version. Publishing needs ≥1 falsifier, ≥1 unresolved question, and owner approval of the Relationships it depends on (ticket 05). The dossier exports as JSON and Markdown.
