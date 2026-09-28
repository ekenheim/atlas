# 12: Hindsight in Compose and bank template

**What to build:** The local stack includes the pinned Hindsight configured like the spike. The research bank is configured from a versioned template (dry run, then import). Readiness covers Hindsight and LiteLLM, and each run records its routed models. Spec Part B: Bank template, LLM route recorder, Configuration, minimal run record; stories 30–33.

**Blocked by:** 11 (Hindsight gateway and recorded fake)

**Status:** done

- [x] Compose adds Hindsight 0.10.1 (the cluster digest) with the spike's settings (2 concurrent LLM calls, 4 worker slots, thinking off, LiteLLM embeddings and rerank)
- [x] The template holds spec §6.2 missions and dispositions; applying is dry run then import, and the version is recorded
- [x] The run record stores code version, Hindsight version, template version and each alias's routed deployment from `/model/info` (faked in CI)
