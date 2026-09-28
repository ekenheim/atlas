# Local dev access to LiteLLM (and a Hindsight space to try)

Type: task
Status: resolved
Blocked by: none

## Question

Reframed 2026-09-28 (Q21): no kubectl. Flux deploys from Git, so live-state checks come from the home-ops repo. What the dev loop needs:

1. **(Human)** Mint a dev virtual key `atlas-dev` via a `LiteLLMVirtualKey` in home-ops, separate from the production `atlas` key, with:
   - a small `maxBudget` / `budgetDuration`
   - a model allowlist: MiniMax-M3, MiniMax-M2.7, `fast`, `translate`, `qwen3-embedding-0.6b`
2. **(Human)** Put the key and the LAN-reachable LiteLLM base URL in the repo's untracked `.env` as `LITELLM_URL` / `LITELLM_API_KEY`. Never commit it or paste it in chat.
3. **(Agent)** From WSL, confirm that LiteLLM answers `/v1/models` with the key, that each allowlisted model serves a non-streaming call, and that SearXNG's JSON API answers. Record the URLs.
4. **Hindsight space:** local Compose runs the pinned 0.10.1 with its LLM pointed at LiteLLM through the dev key (the Q12 decision). A bank on the shared `llm/hindsight` can't run the bake-off, because its server-wide LLM is `openai-codex`. Also, its single tenant key opens every bank.

Resolved when step 3 passes; the answer records the working URLs and where the dev credentials live.

## Answer

Done 2026-09-28.

- LiteLLM: `https://litellm.<domain>`, reachable from WSL. The `atlas-dev` key is in `.env` as `LITELLM_URL` / `LITELLM_API_KEY`; it lists 23 models.
- MiniMax-M3 and M2.7 both pass non-streaming, `json_object`, strict `json_schema` and forced tool-choice calls.
- `qwen3-embedding-0.6b` returns 1024 dimensions.
- SearXNG: `https://search.<domain>`, JSON works. The default engines are partly broken, so name engines explicitly.
- `.env` has CRLF line endings, so config loading must strip values.
- The key appeared once in local tool output because of the CRLF issue; rotating `atlas-dev` is advised.

Details: `docs/research/litellm-dev-probe.md`.
