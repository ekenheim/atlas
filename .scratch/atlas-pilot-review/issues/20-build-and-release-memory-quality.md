# Build and release the memory-quality effort

Type: task
Status: claimed
Blocked by: 19

## Question

Build the spec `.scratch/atlas-memory-quality/spec.md` (sixteen tickets to build, in `.scratch/atlas-memory-quality/issues/`), integrate and release it with the `release-atlas` skill, deploy it, run the backfill for the pilot's companies and show the conformance check passing strict.

- Wave 1 (no blockers): 01 Hindsight 0.10.2 recorded, 02 Memory health and the probe set.
- Out of band, at once: 16 The Editor's card fits a multi-hop investigation. A blocker (investigation 1 on 0.3.0 ended with no card), released by itself as 0.3.1 so investigation 1 can be run again.
- Added from the cluster's consolidation log (2026-10-02): 19 Atlas decides when Memory consolidates (no blockers).
- With this release, from investigation 1's review: pilot-fix tickets 21 (a finding says only what its Claims say), 22 (an analyst's words), 24 (a seed's filings are read) and 26 (the Investigator's answers fit the schema), in `.scratch/atlas-pilot-fixes/issues/`.
- Added after Codex's review (2026-10-02): pilot-fix ticket 29 (every as-of reader uses the corrected availability) and the disclosure part of 25 (the card shows which companies the Skeptic checked).
- Not built: 17 and 18 (news stories through TradingView). Written on the owner's suggestion and dropped with the owner the same day: a news story makes no Claim and no edge.
- Wave 2: 03 A section's outcome (no blocker since the cancellations were confirmed); 04 What a retained section says, 05 The bank template, 06 Observation scopes, 07 Recall as a reading index, 10 Reflect and the models (after 01); 14 The conformance check (after 01, 02).
- Wave 3: 08 Chunk-exact pointers (after 07), 09 The entity hop (after 04, 07), 15 The embedding model (after 01, 14).
- Wave 4: 11 The owner's server settings (after 02, 15; the lead's, the owner merges), 12 The backfill (after 03 to 06, 15).
- Wave 5: 13 Layer-aware pointer recall (after 05, 07, 12).

Each ticket goes to one Opus implementer in its own worktree (`docs/agents/implementer-brief.md`); the lead names the migration revisions, checks each implementer's artifacts against its ticket before merging, integrates, runs the runners and releases. Before the build: the health read and the probe set run on production as the before-measure. After the deploy and the backfill: both again, and `scripts/memory-conformance.sh --strict`.

The answer records the release, the deploy, the before and after numbers, the conformance report and how each implementer's work held up against its ticket.

## Comments

**2026-10-02, the lead: the before-measure of recall** (`.scratch/tools/probe_before.py`, production 0.3.0, 08:10 to 08:40 UTC, read-only, no LLM call; raw answers in `.scratch/live-runs/20261002-memory-probe-before/`, not in git). 91 theme-scoped recalls as Atlas sends them today: the five pilot questions, and 86 Scout queries of investigation 1 on 0.3.0 and of the breadth runs on 0.2.5. None failed.

| | Pilot questions (5) | Scout queries (86) |
|---|---|---|
| Memories per recall, median (range) | 46 (37 to 49) | 42 (34 to 54) |
| Of them observations, median | 15 | 13 |
| Distinct sections pointed at, median | 63 | 50.5 |
| Distinct companies pointed at, median | 3 | 3 |
| Citations resolved / unverified / broken | 224 / 1 / 0 | 3,561 / 42 / 0 |

- Of the 3,828 memories returned in all, 1,313 (34%) are facts returned beside an observation that was built from them: places a recall with `prefer_observations` would give to other sections (ticket 07).
- Every recall is capped near 45 memories by the default `max_tokens` (ticket 07).
- 11 companies are pointed at over the 91 recalls, two of them far more than the rest (3,953 and 3,886 source sections, then 1,793 and 983; three companies under 12). Memory holds little of most companies: about 1,900 sections' retains were cancelled early in the rollout (ticket 12 brings them in).
- The same recalls are run again after the release and the backfill, through ticket 02's probe script, whose report can also be computed from these raw answers.

**2026-10-02 (09:40 UTC), the lead: the before-measure in the probe set's own format** (`scripts/memory_probe.py`, ticket 02; `configs/memory/probes.yaml` version 1: the five pilot questions and four Scout-style queries each, 25 theme-scoped recalls; production 0.3.0; report in `.scratch/live-runs/20261002-memory-probe-before-official/`). This is the table the after-measure is compared with.

| Probe | Memories | Resolved | Sections | Companies | Observations | Superseded |
|---|---|---|---|---|---|---|
| laser-chips | 210 | 209 | 148 | 8 | 21% | 54 |
| inp-substrates | 215 | 215 | 136 | 5 | 21% | 47 |
| module-assembly | 242 | 241 | 179 | 8 | 13% | 17 |
| dsp-drivers | 233 | 223 | 208 | 9 | 16% | 16 |
| coherent-demand | 249 | 248 | 149 | 7 | 22% | 61 |
| total | 1,149 | 1,136 | 405 | 10 | 19% | 195 |

- "Superseded" is a fact returned beside an observation of the same answer that was built from it: 195 of 1,149 places (17%). The lead added the measure after the script's first run: its "repeats" only saw identical text and read 0. (The 34% above came from 91 other queries, most of them investigation 1's.)
- Pointer weight by company over the 25 recalls: Coherent 90.2, Lumentum 78.1, Applied Optoelectronics 27.3, AXT 22.9, MACOM 6.9, Marvell 3.9, Ciena 3.4, Fabrinet 3.2, IQE 0.3, STMicroelectronics 0.02; Soitec and Innolight none. The dsp-drivers and coherent-demand questions are seeded with Marvell, MACOM and Ciena.
- The memory-health read is not on production until this effort is deployed; its before-numbers are the metric's (695 completed, 22 zero-fact, 1,907 recorded failed of which the sampled ones are all the owner's cancellations, 59 pending, at 07:53 UTC).

**2026-10-02 (11:03 UTC), the lead: the conformance check's known answers, before** (`scripts/memory-conformance.sh --only known-answers`, read-only on production 0.3.1, no LLM call; report in `.scratch/live-runs/20261002-conformance-known-answers-before/`). Each pilot question is recalled with its four Scout-style queries, as an investigation's pointer recalls are, and the sections the answers lead to are ranked.

| | Answers | In the top 10 sections | In the top 50 | Ranked beyond 50 | Not pointed at |
|---|---|---|---|---|---|
| All five questions | 23 | 5 | 5 | 6 | 12 |

- **It fails, as a before-measure should:** recall at 10 and at 50 are both 0.22 against the file's first thresholds of 0.25 and 0.5. By question: coherent-demand 2 of 3, inp-substrates 1 of 4, laser-chips 2 of 13, module-assembly 0 of 2, dsp-drivers 0 of 1. A recall returns about 45 memories, so each question's five recalls rank 135 to 209 sections, and twelve known answers are in none of them, among them Lumentum's allocation statement, whose section is in Memory.
- **Two answers did not resolve** and are fixed in the file (version 2): the sentence from Coherent's 10-K was written whole, and the parse Memory was retained from has a page break in the middle of it ("manufacture 9 Table of Contents of transceivers"); the answer is now the part after the break. The five anchors the run found are written in.
- The answers are few where the reviews were thin: dsp-drivers 1, module-assembly 2, no answer for the system hop or the share of the bill of materials. The reviews of investigations 2 to 5 will add theirs.

**Handoff, 2026-10-02 (afternoon): the state of the build, for whoever orchestrates next.** The owner is moving the orchestrator to Opus; the working method stays (Opus implementers and integrators through the Workflow tool, each in its own worktree; the lead audits every artifact against its ticket before merging; memory notes `fable-orchestrates-opus-subagents`, `hindsight-as-advertised-before-benchmarks`, `serenity-method-guides-atlas`).

*Where the code is.* The lead's branch `integrate/mdr` (worktree `C:\Users\ekenh\worktrees\atlas\oval-tide\atlas`) holds, merged and locally green: memory-quality tickets 01 to 07, 10, 14, 16 and 19 (migration chain `0060 → 0061 → 0068 → 0062 → 0063 → 0066 → 0069`, bank template `1.4.0`). `main` is at `a6d28ae` (= `v0.3.1`, live on production). Nothing after `v0.3.1` has run on the runners yet.

*Built, committed on their branches, not merged yet:*
- `worktree-wf_c47f7cd7-0ba-1` (08 chunk-exact pointers, migration 0065) and `worktree-wf_c47f7cd7-0ba-2` (09 the entity hop, migration 0064): both based on `6c17205`; they overlap in the pointers, passage selection and the investigation model.
- `worktree-wf_be4f95ba-b63-1` (pilot fix 21, findings grounded; `editor.v7`), `-2` (22, an analyst's words; migration 0070), `-3` (24, a seed's filings), `-4` (26, extra fields ignored; migration 0072; `investigator.v9`): all based on `af32fc0`, before the wave-2 merge.
- An integrator for these six is launched or to be launched from the lead's head (the next comment says which).

*Next steps, in order:*
1. Merge the integrator's result; re-run the checks; push the tree to the runners as `integrate/mq-a` (`git push origin HEAD:refs/heads/integrate/mq-a`), fix what fails.
2. Small things the lead owes on the tree: tighten the `layer` label group's description in the bank template (the live mission comparison labelled a fact about rare-earth export controls `substrate`: say that a raw material, metal or mineral is no layer); write the comparison note `docs/research/mission-comparison.md` from `.scratch/live-runs/20261002-mission-compare/mission-compare-05.json` (6 MiniMax requests, live, local Hindsight 0.10.2) and tick ticket 05's last box; the health read's per-company view lists no observation scope now that scopes are per theme (ticket 06's note).
3. Ticket 12 (the backfill): give it to an implementer on the integrated tree. It starts by recording delete-then-retain on the local Hindsight (the owner approved local-spike live calls for this effort; cap it at 8 LLM requests). Order: pilot seed companies first, thinnest first; cancelled sections, then transcripts, then the rest.
4. Ticket 15 (the embedding model, measured): the lead runs it on the local Hindsight with the conformance check's known answers; then ticket 11 (the home-ops PR with the server settings; the owner merges).
5. Ticket 13 (layer-aware pointer recall) after 12.
6. Release (the `release-atlas` skill): the template `1.4.0` must ship with tickets 05, 10 and 19 together (the owner set auto-consolidation off by hand on production; the import must keep it). After the deploy: `atlas_retained_sections_total{outcome="cancelled"}` about 1,907; the health read; then the backfill per company; then `atlas memory consolidate`; then the probe set and `scripts/memory-conformance.sh --strict` (its behaviours half makes live calls: a throwaway bank, at most 10 retain operations and 6 LLM-making requests).
7. Then the five verdict runs (`.scratch/tools/pilot_runs.py <n> pilot-<version>`, the review as done for investigation 1: `pilot_review_pack.py`, two blind judges per chunk, the lead adjudicates) and ticket 13 of this map, the verdict.

*What waits for the owner:* edge decisions (ticket 09; the queue holds about 136), the gold cases (ticket 10), the consolidation question (pace the backfill's consolidation on the ChatGPT subscription, or move consolidation to MiniMax server-wide; ticket 01 measured one consolidation request per scope touched), and merges of home-ops PRs.

*The measures to beat* (all in this ticket's comments): the probe set (25 recalls: 1,149 memories, 405 sections, 195 superseded), the known answers (5 of 23 in the top 50 sections), investigation 1 on 0.3.1 (precision 84.6% strict, trust gate and latency failing).

**2026-10-02, the lead: 0.4.1 deployed** (home-ops #7198, then #7197 for Hindsight's extraction-error failure and the rrf fallback; both merged 19:23 UTC). 0.4.0 was published and skipped. 0.4.1 adds `ATLAS_CONSOLIDATION_ENABLED`, which is off in production until the owner chooses how consolidation runs. Checks on production at 19:25 to 19:30 UTC:
- `atlas_build_info{version="0.4.1"}`; `/api/v1/health/ready` is ready, with database, archive, Hindsight and LiteLLM all ok; the queue has no pause and nothing pending.
- Memory health: 3,089 sections. 1,102 completed, 1,907 `cancelled` (migration 0068; 0 failed), 22 zero_fact, 58 pending. 0 at profile and 1,124 below profile, so the backfill has not run yet. No consolidation recorded.
- A live theme recall returns 45 memories. The same query with `scope.layer: substrate` is accepted by Hindsight (`tag_groups`) and returns 0, as expected while no fact carries a layer label; the filter itself is to be checked again after the backfill.
- The backfill starts with the nightly CronJob at 01:30 UTC (at most 300 sections a night). After-measures follow once the seeds are at profile.

**2026-10-03 (09:47 UTC), the lead: the backfill overnight.** Memory health on production: 3,147 sections, 1,542 completed and 15 zero_fact, all 1,557 at profile `retain-v2` (0 below profile, 0 cancelled, 0 failed), 1,590 pending (423 `retain` and 68 `reprocess` jobs queued, backfill class). 37,964 facts. At profile: Applied Optoelectronics, AXT, Ciena, MACOM and Marvell whole; Lumentum 795 of 991, Fabrinet 51 of 98, Coherent 301 of 1,478, STMicroelectronics 3 of 76; IQE (82) and Soitec (15) not started; Innolight has nothing. The `hindsight_minimax` budget holds the backfill (140 of 200 used, backfill limit 140) until 11:36 UTC, so the rest takes about two more nights. One MiniMax 429 (code 2062) at 03:29 UTC, inside Hindsight's extraction: the queue paused for 60 s as a quota failure and cleared, so the extraction 429 now reaches the pause (the 2026-10-02 failure did not). No consolidation yet (`ATLAS_CONSOLIDATION_ENABLED` off; 1,542 sections retained since none). The after-measures wait for the seeds at profile: Coherent and Lumentum are the pilot's largest seeds.
