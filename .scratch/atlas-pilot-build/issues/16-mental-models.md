# 16: Mental models

**What to build:** The researcher can read the Theme status and Bottlenecks mental models, with history and resolved citations. They refresh on a daily schedule and never after consolidation. Spec Part B: Bank template, stories 26–29; CONTEXT.md Bottleneck.

**Blocked by:** 15 (Recall and reflect with resolved citations)

**Status:** ready-for-agent

- [ ] Both models are defined in the bank template; Bottlenecks is worded with the glossary's Bottleneck test
- [ ] The refresh runs as a scheduled daily job with a minimum interval; `refresh_after_consolidation` is off
- [ ] `GET /api/v1/mental-models[/{id}]` returns content, history and resolved citations
