# Memory holds the settled Beliefs

Type: build
Status: open
Blocked by: 02, 05

Spec §3, second seat. A judged Belief is retained as its own Hindsight document (`belief:<id>`, tags `theme:<slug>`, `belief`, `judgement:<value>`; statement, as-of, judgement, load-bearing Fact IDs); a supersession or new judgement replaces it (`memory_replacement`). Recall's provenance resolver labels a belief memory `belief` (resolved to the Belief, never a section). Then measure: do the skill's sessions and the pipeline's Readers reach the right conclusions faster with them (probe recalls before and after)?

## Done when

- [ ] Retain, replace, resolve; tests with the Hindsight fake; a before/after probe recorded in `docs/experiments.md`.
