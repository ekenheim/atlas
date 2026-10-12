# 10: Release and deploy the effort, with luna as the judge in production

Type: task
Status: resolved
Blocked by: 07

## Question

The lead's release work, in the usual way (`release-atlas`): integrate the tickets as they land, chain the migrations, release a tag, open the home-ops PR for the owner to merge. Production settings that go with it: `chatgpt` on the `atlas` LiteLLM key (home-ops-upgrade `keys/atlas.yaml`; the owner merges), `ATLAS_LLM_ROLE_MODELS={"finding_judge":"chatgpt"}` in the Deployment, and later `ATLAS_BULK_RETENTION=off` (after 06 and a few judged Beliefs). Record each deploy in the log; resolve when 09 can run on production.

## Answer

v0.6.1 (main b234134) released on 2026-10-12 and deployed through home-ops-upgrade #7501, merged by the owner; production reports the version with every readiness check ok. 0.6.0 was tagged first and cancelled by its release run. The judge runs on luna (`ATLAS_LLM_ROLE_MODELS`), `chatgpt` is on the `atlas` key. `ATLAS_BULK_RETENTION=off` waits for judged Beliefs in Memory (ticket 06's probe). Ticket 09 can run on production.
