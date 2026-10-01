# Atlas's retains extracted on MiniMax, by Hindsight's metadata routing

Type: prototype
Status: claimed
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

## Comments

**2026-10-01, the lead: prototyped; the owner agreed to metadata routing.** On a throwaway local Hindsight 0.10.2 (the cluster's version) with two LiteLLM models standing in for the members (primary MiniMax-M2.7, member 1 MiniMax-M3) and the strategy `{"mode":"metadata","routes":[{"key":"extractor","value":"minimax","member":1}]}` on the global chain:
- An item with `extractor: minimax` was extracted by member 1; items without the key or with `extractor: other` by the primary. The bank's LLM request log names the model and, in `metadata.document_id`, the document.
- Two items with different routes in one retain batch were each routed correctly.
- With member 1 set to a model that doesn't exist, the routed item's extraction failed after four attempts and its retain operation ended `failed`; nothing fell back to the primary. The unrouted item of the same batch was extracted, and an unrouted batch completed.
- The strategy is accepted at startup. About 12 to 21 seconds per small batch; six retain calls in all on MiniMax.

Not verified: `openai-codex` as the primary of the chain (it can't run locally), and MiniMax's extraction against the Codex-extracted bank (the bake-off measured MiniMax alone: 16 of 17 expected facts).

**Decided:** the metadata key is `extractor`, value `minimax`, sent on every Atlas retain item when `ATLAS_RETAIN_EXTRACTOR` is set; routed retains get their own operations budget and leave the `codex` budget to reflect, mental-model refresh and replay; Atlas records the extractor it asked for on the section's memory record. Built as ticket 11 of `.scratch/atlas-memory-directed-reading/`.

**Cluster side:** home-ops PR #7180 (draft): the second chain member and the strategy on the shared Hindsight, reusing its existing LiteLLM key. Inert until Atlas sends the key. Open for the k8s team: whether that key may call MiniMax-M3.

Resolved when PR #7180 is merged, ticket 11 is released, the setting is on in production and a retained section's request shows MiniMax-M3 in Hindsight's log.

**2026-10-01 (21:15 UTC), the lead: PR #7180 merged by the owner and checked on the cluster.** The shared Hindsight (0.10.2) restarted cleanly with `openai-codex` as the primary and MiniMax-M3 as member 1; its log shows the connection to `openai/MiniMax-M3` verified, so the release's existing LiteLLM key may call that model. In a scratch bank (deleted afterwards), through the shared server's API: an item with `extractor: minimax` was extracted by provider `openai`, model `MiniMax-M3` (3,492 tokens in, 781 out, 12 s); an item without the key by `openai-codex`, `gpt-5.6-luna`; the bank's consolidation ran on `gpt-5.6-luna`. This closes the prototype's open point (a chain whose primary is Codex). Atlas's readiness stayed `ok`. Still to do for this ticket: ticket 11 released and `ATLAS_RETAIN_EXTRACTOR=minimax` set in production.
