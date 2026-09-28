# Choose and pin the extraction and reflect models

Type: grilling
Status: open
Blocked by: 04

## Question

Given the bake-off results, which model serves Atlas Hindsight extraction, and which serves reflect? What is the exact pinned identifier (and, for self-hosted, the weights/quant)? What LiteLLM aliases does Atlas define (`atlas-extract`, `atlas-reflect`, and the per-role aliases for later phases)? What happens when the chosen model is unavailable: fail closed, or a named fallback that is recorded per run?

Inputs from ticket 02 that need the owner:

- pinning Ornith's weights by checksum, and dedicated no-fallback Atlas routes in LiteLLM
- whether MiniMax's name-plus-date counts as a stable identifier
- MiniMax's grey terms for batch use and the quota it shares with coding use (pay-as-you-go would be a new cost)
- whether an Anthropic API key (a new cost) is worth it
