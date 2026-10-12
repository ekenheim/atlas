# A frontier model for the Editor and the finding judge, measured

Type: prototype
Status: open
Blocked by: none

## Why

Every argument-plan round since 0.5.3 has left the trust gate failing at the same rate (13–14% of statements): merged dates, dropped qualifiers, a plan written as a fact, an inference added to a faithful quote. These are writing and judging errors, and MiniMax-M3 does all of the writing and all of the judging (`ATLAS_LLM_ROLE_MODEL` is one model for every role). "A frontier model for the Editor and judge" has been priority 6 since 2026-10-07 and was never tried. The Editor and the judge together spend about 100k tokens a question, so a stronger model there costs little next to the Readers' 1.8M.

Approved by the owner on 2026-10-12 (this session).

## What to measure

1. **Offline first, the judge alone:** `.scratch/tools/finding_judge_eval.py --argument` on the 130 labelled 0.5.3 statements (17 failing), once with MiniMax-M3 (the recorded baseline) and once with a frontier alias in LiteLLM (whichever the owner has: a Claude or GPT alias; record the deployment from `/model/info`). Report caught of 17 and flagged of 113 for each. Also pool the 0.5.4–0.5.6 label files if `argument_statement_labels.py` can build them.
2. **Offline, the Editor:** `.scratch/tools/editor_replay.py` on two saved cards' Facts (question 2, the best, and question 5, the worst), both models; the lead reviews the statements against their quotes with the same trust-gate rubric. Report overstatements per statement.
3. **Live, only if 1 and 2 show a gain:** questions 2 and 5 on production with the Editor and judge on the frontier alias and the Readers on MiniMax, the blind double review as before. Compare with the 0.5.4/0.5.6 rows in `.scratch/pilot/results.md`.

## What to build (small)

A per-role model override: `ATLAS_LLM_ROLE_MODELS` (a `role=alias` map, e.g. `editor=…,finding_judge=…`), falling back to `ATLAS_LLM_ROLE_MODEL`; recorded on every role call so a run says which model wrote what. Unit test at the settings seam and the role caller. No prompt changes in this ticket: the question is the model, held constant otherwise.

## Done when

- [x] Step 1's numbers are in `docs/experiments.md` ("2026-10-12: a frontier model as the finding judge"): MiniMax 5 caught / 11 flagged, luna 11 / 26, astra 14 / 24 of 17 and 113.
- [ ] Step 2's review is in `.scratch/pilot/results.md`.
- [x] Decision: the judge moves to luna; astra parked for the judge; the Editor's model question is superseded by the Claude-session direction (`.scratch/atlas-beliefs/spec.md`).
- [ ] If moved: the override released and the model recorded per role call.

## Comments

**2026-10-12, the override built:** branch `ticket/25-per-role-model` (commit e38afea, a Sonnet implementer; the lead reviewed the diff): `ATLAS_LLM_ROLE_MODELS` (JSON object, role name to LiteLLM alias), chosen per call and recorded in `role_call.model`; no migration. Tests: `tests/unit/test_settings.py`, `tests/integration/test_role_calls.py` (71 passed locally). To check at measurement time: `ATLAS_LLM_ROLE_EXTRA_BODY` (thinking disabled, for MiniMax) is merged into every request, so a frontier alias needs LiteLLM to drop or accept that field. Step 1 (the offline judge eval) waits on a frontier alias and a LiteLLM key from the owner: none is configured on the lead's machine or worktrees.

**2026-10-12, the model under test:** the LiteLLM proxy has no Claude alias; its single-deployment frontier aliases are `frontier-pool` (chatgpt/gpt-6-astra, flagship rate on the owner's shared ChatGPT plan) and `chatgpt` (gpt-5.6-luna, cheap). The owner accepted astra for the test, reluctantly, on cost. So: stage 1, the judge on the 17 failing statements plus 30 passing ones (47 calls), MiniMax-M3 beside it; stage 2, the full 130 only if stage 1 shows a gain; then one luna pass if astra gains, to see whether the cheap model is enough. Key: home-ops-upgrade #7479 (`atlas-eval`). The `chatgpt/` aliases serve streaming callers only, so the caller gains `ATLAS_LLM_ROLE_STREAM_MODELS` (a second implementer, on top of the override).

**2026-10-12, measured:** see `docs/experiments.md`. Left for the release: `chatgpt` on the `atlas` key, `ATLAS_LLM_ROLE_MODELS={"finding_judge":"chatgpt"}` in the deployment, and the bridge's HTTP 500 ("Unknown items in responses API response") classified transient so the caller retries it (about 7% of calls). Step 2 (the Editor replay on astra) was not run: the owner moved the writing to Claude sessions the same afternoon; the tool `.scratch/tools/argument_editor_replay.py` is on branch `worktree-agent-aedf914c4624167e0` if wanted.
