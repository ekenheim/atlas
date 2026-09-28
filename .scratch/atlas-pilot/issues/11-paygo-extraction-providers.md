# Pay-as-you-go extraction providers: Kimi, MiniMax, Anthropic, GLM

Type: research
Status: resolved
Blocked by: none

## Question

Coding and consumer subscriptions (ChatGPT Plus, the Anthropic consumer plan, MiniMax Plus) are a poor or disallowed fit for automated batch extraction (ticket 02). For each pay-as-you-go API option, what are:

- current per-token prices
- whether it offers a **dated or snapshot model ID**
- JSON-schema structured output and forced tool choice (Hindsight 0.10.1 reflect uses forced tool calls)
- non-streaming support
- terms for automated server-side and batch use
- data-retention / training-on-inputs policy
- LiteLLM provider support

Options:

- Moonshot Kimi API (K2.x / K3), plus whether a Kimi subscription plan permits API or batch use
- MiniMax pay-as-you-go
- Anthropic API (Claude Haiku 4.5 has the dated ID `claude-haiku-4-5-20251001`; Sonnet 5)
- Zhipu GLM API

Rough scale for pricing: Phases 0–2 extract two companies' filings over 2–3 years, likely a few million input tokens in total.

## Closed: out of scope

The owner ruled out pay-as-you-go providers (2026-09-28): the subscriptions already paid for are to be used, with their terms ambiguity and model drift accepted. The research was stopped before it produced findings.
