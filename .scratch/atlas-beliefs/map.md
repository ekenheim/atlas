# Map: Beliefs, Issues and the session as researcher

Label: wayfinder:map

## Destination

The revised method built, deployed and proven: a Claude session researches a bottleneck question with Atlas's tools, its statements judged by Atlas before they become Beliefs; Beliefs, Issues and sessions are recorded and audited; judged Beliefs live in Memory; the website leads with what Atlas believes. Reached when question 2 is re-run as a session with the judge loop, scored by the pilot's procedure at or above the proof's precision and with the trust gate at or below the pipeline's rate, and its Beliefs are on the theme page in production.

## Notes

- **Spec:** `spec.md` (ready-for-agent); glossary `CONTEXT.md`; deviations in `docs/decisions.md`; the owner's approval of the revision and its page, 2026-10-12 (https://claude.ai/artifact/5WrVWvPLAuXgDEt2xEbmgB).
- **This map carries execution,** like the pilot-review map before it: its tickets are build slices, each vertical (schema, API, page, tests) and demoable on its own, handed to implementers by the lead with `docs/agents/implementer-brief.md`; the lead reviews, integrates (`integrate/<name>`, CI, fast-forward main) and releases with `release-atlas`. The pilot-review map's unrun pipeline tickets are superseded by this effort.
- **Who decides:** the owner delegated planning, scope and the review loop to the lead; the owner's own acts are merging home-ops PRs, credentials and keys, spending beyond the agreed budgets, judgements the owner wants to set personally, and every financial bet.
- **Models and cost:** sessions run on the Claude subscription (Opus researches, the lead reviews; Sonnet implements); the judge on `chatgpt` (gpt-5.6-luna) through LiteLLM; MiniMax and the local GPU for volume; astra parked. The OpenAI 5 h window and the Claude week are the budgets to watch; a session is capped like the researcher's hour.
- **Standing rules:** Memory is derived, never Evidence; a Belief cites Facts and Facts cite spans; only an author sets a judgement; pages are dark, terse, never show commands, and lead with the assessment; nothing depends on the owner's 5090.
- **Order of work:** 07, 08 first (independent); then 02; then 03, 04, 06 (independent); then 09 (the closing measure) and 10 (the release). 01 is the owner's.

## Decisions so far

<!-- one line per closed ticket -->

- [The revision, proven](issues/05-the-atlas-research-skill.md) (2026-10-12): two Opus sessions with the `atlas-research` skill beat the pipeline on reading (Facts 100% and 93% right against 75%; 19 of the researcher's 32 facts on the card against 8; AXT reached as of 2025-08-31 with the early signal in substance) at a tenth of the tokens; the trust gate is the one measure not better, with no judge applied. The owner took the revision.
- The judge (pilot-review ticket 25, 2026-10-12): on the same prompt and 130 labelled statements MiniMax catches 5 of 17 misstatements, luna 11, astra 14; luna judges, astra is parked; the per-role override `ATLAS_LLM_ROLE_MODELS` is on main.
- The AXT replay (pilot-review ticket 26, 2026-10-12): both the session and the pipeline reached AXT; the session stated the point in substance, the pipeline did not; no leakage past the cutoff in either.

## Not yet specified

- **Scheduling sessions** (in the cluster's agent-lab or as cloud routines) once the judge loop and the pages exist; which questions a scheduled session takes (the Issue frontier) and how its output is reviewed before a judgement.
- **Hypotheses and Beliefs.** A Hypothesis version's findings become Beliefs; whether the Hypothesis stays as the published, snapshotted bundle of Beliefs (likely) or merges into them; the publish gate's Belief rule in detail.
- **Retiring the default plan and the pipeline's edge review** (57% right) once Beliefs are the record; what of Relationships survives as evidence for Beliefs.
- **Switching bulk retention off**: when (after 06), and what the research bank keeps of the 70k extracted facts (nothing is deleted; whether old observations are retired).
- **The second theme** (memory and packaging, ranked first on the pilot map) as the first use of Issues across themes; the layer taxonomy per theme.
- **Trackinizer** as the graph view, when the owner's projection (01) has been judged.
- **The bar for sessions**: the pilot's criteria apply; whether faithfulness and on-question share are reported beside precision (the withdrawn revision proposal) is decided when 09 reports.

## Out of scope

- Automated judgement of Beliefs; a planner beyond the next-action rule; portfolio sizing; price data; return measurement.
- Replacing Hindsight; a fork of trackinizer.
- The pipeline's formal five-question verdict (closed with `docs/pilot-report.md` and the proof; no more MiniMax verdict runs).
