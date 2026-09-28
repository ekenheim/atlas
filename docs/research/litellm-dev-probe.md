# LiteLLM and SearXNG dev-access probe (2026-09-28)

Live calls from WSL through `https://litellm.<domain>` using the `atlas-dev` key (`LITELLM_URL` / `LITELLM_API_KEY` in the untracked `.env`). These are single small calls, not an extraction benchmark.

| Check | MiniMax-M3 | MiniMax-M2.7 |
|---|---|---|
| Non-streaming chat | ✅ | ✅ |
| `response_format: json_object` | ✅ valid JSON, 5.4 s | ✅ valid JSON, 9.3 s |
| `response_format: json_schema` (strict) | ✅ valid JSON, 3.9 s | ✅ valid JSON, 7.3 s |
| Forced `tool_choice` (function) | ✅ 1 call, valid args, 1.2 s | ✅ 1 call, valid args, 5.6 s |
| Response `model` field | alias (`MiniMax-M3`) | alias (`MiniMax-M2.7`) |
| `x-litellm-model-id` header | present (deployment hash) | present |

- **Output handling:** the probe stripped a `</think>` prefix and code fences before parsing JSON content. Whether Hindsight tolerates raw MiniMax output is for the bake-off (ticket 04) to show.
- **Embeddings:** `qwen3-embedding-0.6b` → 200, 1024 dimensions.
- **Models visible to the key:** self-hosted, review, fast, translate, deep, chatgpt, MiniMax-M3, MiniMax-M3-chat, MiniMax-M2.7, kimi-k2.7, kimi-k3, glm-5.3, glm-5.3-flash, frontier-pool, reasoning-pool, implementation-pool, local-pool, local-pool-chat, auto, qwen3-embedding-0.6b, rerank, gemma4:e4b, qwen3.8:latest.
- **SearXNG:** `https://search.<domain>/search?format=json` → 200 JSON. With the default engines a query returned 0 results: duckduckgo gave a connection error, qwant/startpage parsing errors, and wikidata access denied. With `engines=duckduckgo,bing,brave` it returned 20 results. The Phase 3 adapter should name engines explicitly and record `unresponsive_engines`.
- **`.env` line endings:** `.env` on the Windows filesystem has CRLF line endings, so values must be whitespace-stripped when loaded.
