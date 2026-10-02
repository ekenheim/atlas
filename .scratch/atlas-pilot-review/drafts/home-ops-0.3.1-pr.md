## What

**Atlas 0.3.1** (`ghcr.io/ekenheim/atlas:0.3.1`): a patch release with one fix. The first investigation on 0.3.0 ended with no research card: with six Investigators it accepted 89 Claims, and the Editor's answer was cut off at its 4,096-token output cap on every attempt.

- A cut-off answer is now its own outcome (`truncated`) for every role: no repair is sent at the same cap.
- The Editor's first cap is 8,192 tokens; a cut-off answer is asked once more at up to 16,384 (`ATLAS_EDITOR_MAX_OUTPUT_TOKENS`, the default).
- The Editor cites Claims by a short reference (`c1`, `c2`, …) instead of 36-character IDs; code maps them back.
- If the Editor still fails, the investigation ends with a card written by code (no finding, the accepted Claims by company, the reason), never without one.

## Manifest changes

- Image `0.3.0` → `0.3.1` in `deployment.yaml` and `ingest.yaml`.
- `ATLAS_LLM_ROLE_TIMEOUT_SECONDS` = `360` (new; the default is 180). MiniMax-M3 writes about 75 tokens a second, so a 16,384-token answer can take longer than 180 s. A timeout is read as an outage and pauses the queue, so the larger cap needs the longer deadline. Every other role keeps its cap; their calls finish far inside either value.
- No new secret.

## Provenance for `ghcr.io/ekenheim/atlas:0.3.1`

- **Source:** tag `v0.3.1` at commit `a6d28ae` on `ekenheim/atlas` main.
- **Release build:** https://github.com/ekenheim/atlas/actions/runs/36990029189 (success: `ci` 26m31s on the self-hosted runners, `publish` 1m26s).
- **CI on the same commit:** https://github.com/ekenheim/atlas/actions/runs/36985943450 (success: 1,409 tests passed, the frontend gates, the API client check, the e2e 10 passed), and main's own run https://github.com/ekenheim/atlas/actions/runs/36990023143 (success).
- **Migration:** one, `0060 → 0061`, not destructive: `role_call.status` accepts `truncated` (the CHECK constraint is replaced by one with the extra value; no row changes).
- **Why 0.3.1:** a patch after 0.3.0; no version was skipped.
- **Checked against the real failure before the release:** the production request that failed (89 Claims) was replayed once against MiniMax-M3 with the new prompt: a valid card in one call, 3,181 output tokens against the 8,192 cap, 40 seconds.

## Load

No change in what Atlas asks of the shared Hindsight. An investigation's Editor call may now use up to 16,384 output tokens once, inside the run's 2,000,000-token budget.

## How to check after merge

`atlas_build_info{version="0.3.1"}`, `/health/ready` all `ok`. The lead then runs pilot investigation 1 again; it should stop with a research card.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
