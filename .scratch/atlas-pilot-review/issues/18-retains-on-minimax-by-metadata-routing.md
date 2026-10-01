# Atlas's retains extracted on MiniMax, by Hindsight's metadata routing

Type: prototype
Status: open
Blocked by: none

## Question

Memory's intake is limited by the ChatGPT subscription: the shared Hindsight extracts on Codex (`gpt-5.6-luna`), the quota is shared with hermes, the Codex CLI and LiteLLM's ChatGPT alias, and Atlas rations itself to 40 operations per 5 h. On 2026-10-01 production had 473 sections retained, 1,907 recorded as failed and 44 retains held by that cap; none of the 43 new transcripts is in Memory. The owner asked whether Hindsight could alternate between ChatGPT and MiniMax, the subscription now dedicated to Atlas.

It can't be done in LiteLLM: Hindsight calls ChatGPT through its own `openai-codex` provider, because LiteLLM's ChatGPT route only works streaming. Hindsight itself has the feature (pinned docs, `references/developer/configuration.md`, "Multi-LLM Strategies"): extra LLM members by index and a strategy, per operation if wanted (`HINDSIGHT_API_RETAIN_LLM_*`):
- `failover`: Codex first, the next member when it fails;
- `round-robin`, with weights: alternate;
- `metadata` (retain only, since 0.10.0): each retained item goes to the member its own metadata selects; everything else uses the primary.

The first two are server-wide, so hermes' content would sometimes go to MiniMax, which the standing rule forbids (`.scratch/atlas-pilot/map.md`, "LLM failover for Hindsight"). Metadata routing sends only the items Atlas marks to MiniMax and leaves every other bank on Codex, with no dedicated Hindsight. Recall, reflect, consolidation and mental-model refresh stay on the primary.

Prototype it before any cluster change (the feature is in the docs, not in `docs/hindsight-feature-matrix.md`):
1. On the Compose Hindsight (the cluster runs 0.10.2), configure a second member for MiniMax (through LiteLLM as an `openai` member, or Hindsight's own `minimax` provider) and `{"mode": "metadata", "routes": [...]}` on the retain chain; retain two fixture sections, one with the routing key and one without; confirm from Hindsight's LLM request log which model extracted each, that the facts and their provenance resolve as today, and what happens when the routed member fails (does the item fail, or fall through to Codex?).
2. Measure on the bake-off fixture: facts found, time per section, tokens, against the Codex-extracted bank.
3. Decide: the metadata key Atlas sends on a retain item (a constant key such as `extractor`, since routes match a key and a value); which retains are routed (all, or backfill only, keeping interactive retains on Codex); how the queue budgets them (they would spend the MiniMax window that the research roles also use, while consolidation still spends Codex); and how Atlas records which model extracted a section, since Hindsight stores nothing about the route.
4. Write the home-ops change for the shared Hindsight (the member, its credentials, the strategy) for the owner to review; it changes a server other banks use.

The local run spends a little MiniMax quota and needs the owner's LiteLLM credentials on this machine. The answer records what was verified, the measurements and the decisions; the build work becomes tickets.
