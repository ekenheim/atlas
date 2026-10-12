# The research session is the researcher; Atlas keeps the record

Atlas's method changes hands. Until now the pipeline did the research: roles on a weaker model (MiniMax) scouted, read, extracted Claims and wrote a card per investigation, over a Memory that was fed every section of every filing. From now on a research session (a Claude session using Atlas's archive, Facts and Memory as tools) does the research, and Atlas is the substrate, the gatekeeper and the record. The pipeline's argument plan is kept as the bulk mode. The spec is `.scratch/atlas-beliefs/spec.md`; the effort's tickets are in `.scratch/atlas-beliefs/issues/`.

## Context

- The pilot (`docs/pilot-report.md`; `.scratch/pilot/results.md` to 0.5.6) showed that the evidence substrate holds: every quote is verbatim at an archived span, with the date it became public. It showed that the argument plan beats the default plan. It also showed that the MiniMax role pipeline loses to one strong agent with a search box, at a tenth of the tokens.
- The proof sessions (`.scratch/pilot/results.md`, "The proof sessions", 12 October 2026) ran a Claude session with the `atlas-research` skill on the same question. Its recorded Facts were 100% and 93% right against the pipeline's 75%; it held 19 of the researcher's 32 facts on its card against 8; from Coherent and Lumentum as of 31 August 2025 it reached AXT and stated the early signal in substance. Its weak measure was the trust gate (8% and 29% of statements said more than their quotes), because no judge was applied to its statements.
- The judge measurement (`docs/experiments.md`, 12 October 2026): on one prompt and 130 labelled statements, MiniMax-M3 caught 5 of 17 misstatements, gpt-5.6-luna 11, gpt-6-astra 14. Luna judges.
- Memory's measured contribution as the reading index is small (known-answer recall 0.08), and consolidating every section produced one-fact observations while costing most of the quota incidents.
- What Atlas lacks is a layer that holds what it believes: perishable cards written by a weak model are not the owner's assessment of anything. Trackinizer's model (Apache 2.0) names the layer: one proposition with an author's judgement, cited with a signed weight, falsified by one load-bearing counter-artifact, superseded without loss, flagged when a cited artifact changes.

## Decision

- **A Belief is the unit of what Atlas holds.** One falsifiable proposition, with an author's judgement and confidence, citing Facts with a signed valence and a weight. A Belief cites Facts, Facts cite spans, and nothing else counts. A proposal must carry a load-bearing citation of positive valence. The judgement is set only by an author through `POST /beliefs/{id}/judge` (the actor is recorded); roles and jobs never call it, and the valence is recorded, never computed. A Belief is born `unproven`. Its history is insert-only and a superseded Belief keeps its citations and its history. Code raises flags (a cited document revised without the quote, a cited Assertion disputed or superseded, a load-bearing citation at valence -0.75 or below that stands) through the proposed-updates trigger path; only an author's judgement clears them. This adopts trackinizer's rules (a signed valence, "the system never forms the verdict", lossless supersession), not its software.
- **An Issue is work.** Open research questions are kept as Issues that narrow and require each other, and the next action is chosen by rule, not by a planner.
- **A Research Session is recorded.** A session registers itself (question, theme, seeds, as-of, model, actor), records Facts through the existing route, proposes Beliefs and Issues through the API, and closes with its usage and card. The pipeline's investigation is a session of kind `pipeline`, so both appear in one list.
- **Memory holds what was found.** A judged Belief is retained into the research bank as its own document; bulk retention of every section can be switched off once Beliefs feed Memory (reversibly; the pipeline stays as the bulk mode).
- **The website presents the findings.** The owner reads the Beliefs of a theme by step and judgement, each opening to its quotes at their spans with their dates, the history, the flags and what supersedes it. Records sit one click deeper than the assessment.
- **The Claude subscription runs the research;** the weaker models are measured later for what can drop to them, after the objective is met on the strong one.

## Consequences

- The vocabulary gains **Belief**, **Issue** and **Research Session** (`CONTEXT.md`). Agents say "investigation" only for the pipeline's run.
- The `atlas-research` skill proposes Beliefs through the API (`belief propose|cite|supersede`) instead of writing a file only; the owner or an author judges them.
- The method is theme-independent: a Belief names a theme and a step, not a photonics layer.
- The trust gate (statements that say more than their quotes) moves from a measure of the card to a rule before a Belief: Atlas judges each statement against its cited quotes before a session may propose it (a later ticket in the effort).
- The pipeline, its roles and the edge review are kept, not retired. Retiring any of them takes a later decision and its own ADR.
- Bulk retention and consolidation are not removed. Switching them off is a setting the owner turns when Beliefs feed Memory.
- Reversing this means the Belief tables stay as a record and the pipeline's card is again the product; no data is lost either way.
