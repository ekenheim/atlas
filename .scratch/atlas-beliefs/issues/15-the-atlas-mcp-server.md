# 15: The Atlas MCP server

Type: build
Status: in-review
Blocked by: 14

## What to build

`backend/atlas/mcp/`: an MCP server (streamable HTTP; the `mcp` Python SDK if its pins fit, else a thin implementation mirroring `atlas.tradingview.mcp`) mounted under the API (`/mcp`) and runnable as `uv run atlas mcp`, exposing typed tools over the existing routes with no logic of their own: `companies`, `search` (as-of), `read` (refuses a version after the session's as-of), `locate`, `record_fact`, `judge_statement`, `relate_facts`, `propose_belief`, `cite_belief`, `supersede_belief`, `open_issue`, `narrow_issue`, `complete_issue`, `next_issue`, `recall` (bank, available_by), `open_session`, `close_session`, `get_fact`. Each call carries the session id; the server records tool calls on the session (`session_tool_call`, insert-only) so a session's usage is Atlas's count, not the agent's. The skill's SKILL.md names the MCP tools; `atlas_tools.py` becomes a thin client over the same routes or is retired.

## Acceptance criteria

- [x] HTTP-seam tests: the tool list, one call per tool against the fakes, the as-of refusal, the session's recorded calls.
- [ ] A Claude Code session with the server configured runs question 2 without the script (the lead), scored.
