# 01: Hindsight 0.10.2 recorded: every feature this effort uses

**What to build:** The lead and every later ticket can rely on observed behaviour of the cluster's Hindsight version for each feature the spec uses, instead of the docs' word. The feature matrix names the version the cluster runs, each feature has a recorded request and response, the recorded fake serves them, and the study's four open questions have answers.

Spec: `.scratch/atlas-memory-quality/spec.md` ("The ground: Hindsight 0.10.2, recorded"). Study: `docs/research/hindsight-memory-use.md` ("Not settled"). Prior art: `spikes/hindsight/` (`feature_check.py`, `feature_followup.py`, `recordings/`, `run.sh`), `docs/hindsight-feature-matrix.md`, `tests/fakes/hindsight.py`.

- The spike's Compose runs the cluster's image (`ghcr.io/vectorize-io/hindsight-api:0.10.2-slim`, the digest in home-ops `kubernetes/apps/llm/hindsight/app/helmrelease.yaml`); synthetic documents as before (fictional companies), MiniMax-M3 with thinking off through LiteLLM, the cluster's embedding model.
- Record, under `spikes/hindsight/recordings/` in a folder per feature: retain with an explicit `observation_scopes` list and `GET …/observations/scopes`; recall with `max_tokens`, `types`, `prefer_observations`, `include.source_facts`, `include.chunks`, `query_timestamp`, and a result's `scores`; retain with `entities` and `resolve_entities: false`, and the entities that result; a bank with an `entity_labels` group (`tag: true`) and a recall filtered by the label's tag; `GET …/memories/list?entity_id=` with a tag and a date filter; `POST …/memories/dry-run-extract`; reflect with `budget` and with `exclude_mental_models`; a tagged mental model seen (or not) by a tag-scoped reflect; a document's `reprocess`.
- Settle and write into the matrix: (a) whether a stored document takes a new scope, context, entities or labels through `reprocess` or a re-consolidation, or must be retained again under the same `document_id`; (b) whether a chunk's text is a verbatim slice of the retained content, and how its offsets can be had; (c) how many LLM requests consolidation makes per retained item with one scope and with two (the per-bank LLM request log); (d) what differs between 0.10.1 and 0.10.2 for the features already in the matrix (re-run the existing checks; list every changed verdict).
- Extend `tests/fakes/hindsight.py` to serve the new request and response fields from the recordings; each derivation beyond a recording is listed in `docs/decisions.md` like the earlier ones. No Atlas behaviour changes in this ticket.
- Re-vendor `.agents/skills/hindsight-docs/` at the server's version if upstream has that tag; otherwise say so in the skill's Atlas note and keep 0.10.1.
- Caps: at most 60 LLM requests in all, counted from the bank's LLM request log and reported; the bank is deleted at the end.

This ticket makes live calls to a local Hindsight and to MiniMax through LiteLLM. The owner approved it on 2026-10-02.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] The matrix is headed with 0.10.2 and has one row per feature above, each with its verdict and its recordings; the four questions are answered with the evidence.
- [ ] The existing matrix rows were re-run on 0.10.2; changed verdicts are listed (or "none").
- [ ] The fake serves each new field; the existing contract tests pass, and one test per new field replays its recording through the gateway's transport.
- [ ] The LLM request count of the run is in the implementation log, with what was live and what was not.
- [ ] `docs/decisions.md` records anything that changes the spec's design (for example: scopes cannot be changed without retaining again).
