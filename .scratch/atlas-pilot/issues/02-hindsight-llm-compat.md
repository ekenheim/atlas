# Which LiteLLM routes can Hindsight 0.10.1 use for extraction, given what we already pay for?

Type: research
Status: open
Blocked by: none

## Question

All LLM traffic goes through LiteLLM, and that includes Atlas Hindsight's extraction and reflect calls. For Hindsight 0.10.1, what does the LLM need from an OpenAI-compatible endpoint: non-streaming calls, structured output / JSON mode / tool calling, and the provider setting for a LiteLLM base URL? Given that, which LiteLLM routes backed by these can serve the dedicated Atlas Hindsight, technically **and** under their terms of use for automated server-side calls:

- MiniMax Plus (`MiniMax-M3` via the cluster LiteLLM)
- self-hosted models behind LiteLLM (`self-hosted`, `local-pool`, ornith-35b, gemma3-27b)
- the Anthropic subscription (which LiteLLM route, if any, backs it today)
- ChatGPT Plus (the `chatgpt/*` rungs are known to fail on non-streaming calls; check whether any LiteLLM configuration fixes that)

Also: does each candidate have a stable model identifier (dated ID, or pinned weights/quant for self-hosted), and does LiteLLM expose the concrete routed model so it can be recorded per run?

Sources: the Hindsight source at the 0.10.1 tag (the LLM provider module), the LiteLLM docs, the MiniMax and Anthropic terms, and `/mnt/c/Users/ekenh/home-ops-upgrade/kubernetes/apps/llm/litellm/app/configmap.yaml` for the concrete routes.
