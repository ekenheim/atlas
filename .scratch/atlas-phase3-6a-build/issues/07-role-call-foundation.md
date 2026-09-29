# 07: Role-call foundation

**What to build:** Every research role (Scout, Investigator, Reviewer, Skeptic, Analyst, Editor) calls the LLM the same way: through LiteLLM with the `atlas` key, a strict JSON schema, Pydantic validation, one bounded repair retry, then quarantine. Each call records routed model, tokens, `metadata.run_id` and role, and counts against a per-run token budget. Retrieved text is always passed as quoted, low-trust data.

Spec: `.scratch/atlas-phase3-6a/spec.md`.

**Blocked by:** None (can start immediately)

**Status:** done

- [x] A role-call module with versioned prompts in the repo and fixed directives in code
- [x] A LiteLLM chat fake in `tests/fakes/` scripting schema-valid, malformed and failing responses
- [x] Malformed output is repaired once then quarantined (visible, never used); transient failures use the existing queue pause
- [x] Usage is recorded per call and summed per run; exceeding the budget raises a typed budget error
- [x] No live LLM calls in CI
