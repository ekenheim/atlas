# Which LiteLLM routes can Hindsight 0.10.1 use for extraction, given what we already pay for?

Type: research
Status: resolved
Blocked by: none

## Question

All LLM traffic goes through LiteLLM, and that includes Atlas Hindsight's extraction and reflect calls. For Hindsight 0.10.1, what does the LLM need from an OpenAI-compatible endpoint: non-streaming calls, structured output / JSON mode / tool calling, and the provider setting for a LiteLLM base URL? Given that, which LiteLLM routes backed by these can serve the dedicated Atlas Hindsight, technically **and** under their terms of use for automated server-side calls:

- MiniMax Plus (`MiniMax-M3` via the cluster LiteLLM)
- self-hosted models behind LiteLLM (`self-hosted`, `local-pool`, ornith-35b, gemma3-27b)
- the Anthropic subscription (which LiteLLM route, if any, backs it today)
- ChatGPT Plus (the `chatgpt/*` rungs are known to fail on non-streaming calls; check whether any LiteLLM configuration fixes that)

Also: does each candidate have a stable model identifier (dated ID, or pinned weights/quant for self-hosted), and does LiteLLM expose the concrete routed model so it can be recorded per run?

Sources: the Hindsight source at the 0.10.1 tag (the LLM provider module), the LiteLLM docs, the MiniMax and Anthropic terms, and `/mnt/c/Users/ekenh/home-ops-upgrade/kubernetes/apps/llm/litellm/app/configmap.yaml` for the concrete routes.

## Context

Research in progress on branch `research/hindsight-llm-compat`; findings in `docs/research/hindsight-llm-compat.md` on that branch.

## Answer

From source and docs only; nothing was live-tested.

**What Hindsight 0.10.1 needs:** non-streaming calls; JSON output for extraction; tool calls, including forced tool choice, for reflect. Pointing it at LiteLLM means `provider=openai` plus the base URL. Extraction and reflect have separate model settings.

**Viable for the bake-off (ticket 04):**
- **MiniMax-M3 / M2.7:** non-streaming works. Neither model documents JSON-schema output or forced tool choice, so expect prompt-only JSON. There is no dated model ID, only a name.
- **Ornith via the `fast` alias:** non-streaming works and JSON is enforced. But the name `ornith-35b` survived an in-place weight swap from 1.0 to 1.5, and the weights aren't pinned by checksum.
- **Gemma 3 via the `translate` alias:** the only local model with pinned weights. Extraction only: its window is small and tool calling is doubtful.

**Not viable:**
- ChatGPT: `chatgpt/*` fails on non-streaming calls on LiteLLM v1.103.0; the `/v1/responses` workaround loses JSON format, and model IDs drift.
- Anthropic: there is no LiteLLM route, and the Consumer Terms forbid automated use without an API key.
- Kimi/GLM are unpaid, and `local-pool*` silently falls back to MiniMax.

**Owner decisions surfaced (→ ticket 05):**
1. Pin Ornith's weights by checksum and add dedicated no-fallback Atlas routes (home-ops changes).
2. Does MiniMax's name-plus-date count as a stable identifier?
3. MiniMax's terms are grey for heavy batch use: pay-as-you-go is recommended there (a **new cost**), and the Plus quota is shared with coding use.
4. Anthropic would need a paid API key (a **new cost**).

**Recording the routed model:** LiteLLM rewrites the response `model` to the alias. `x-litellm-model-id` headers and the spend logs carry the real deployment. Atlas can't see Hindsight's headers, so recording Hindsight's concrete model needs the spend logs (→ fog).

Full findings: `docs/research/hindsight-llm-compat.md` on branch `research/hindsight-llm-compat` (`5ae02a0`).
