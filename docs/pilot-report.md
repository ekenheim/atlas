# The pilot report

Atlas's research pilot, five investigations on production 0.4.6, run and reviewed on 2026-10-07 under the frozen procedure (`.scratch/pilot/verdict-procedure.md`) and the criteria of pilot-review ticket 02. The full reviews, with every span: `.scratch/pilot/results.md`, "The verdict runs on 0.4.6".

## The verdict: fail

No investigation meets the bar. The trust gate fails in four of five: the Editor's findings say more than their Claims. Pooled Claim precision is 63% (bar 80% per investigation), baseline coverage 22% (bar 50%), and machine-reviewed edge precision 57% (bar 90%). Under ticket 02, a fail means no fix round: the research workflow's design is reopened, starting with what the Claim model and the roles can express, before anything else is built.

The comparison that decides the direction is the researcher's hour. One agent with web search and the archive's term search, under an hour per question, found 144 cited, true, on-question facts across the five questions. The cards had 16 of them (11%). Everything the cards counted as saved work was also in the researchers' answers.

What holds: every accepted quote is verbatim at an archived, dated span (364 of 364), and two blind reviewers agree at kappa 0.77 to 0.86.

## Method

- **Version:** production 0.4.6 throughout; no deploy, template import or setting change between the first run and the last. The preconditions are recorded with their times: memory health, consolidation complete, reconciliation clean, queue.
- **The questions:** the pilot plan's five, verbatim, each with its seeds (`.scratch/pilot/pilot-plan.md`), a 2,000,000-token budget, run one at a time, alone on production.
- **The criteria:** ticket 02 (`.scratch/atlas-pilot-review/issues/02-pilot-verdict-criteria.md`), with its comments:
  - cost at most 2,000,000 MiniMax tokens;
  - latency at most 20 minutes;
  - a wrong layer makes a Claim wrong, an unconfirmed one doesn't;
  - a magnitude hit is covered only at its level of detail.
- **The review:**
  - every accepted Claim judged twice, blind, by Opus reviewers; the lead adjudicated every disagreement, confirmed every Claim both called wrong and a random 10% of those both called right;
  - the card, the archive-search baseline (`scripts/pilot_baseline.py`), the run and a researcher's hour each reviewed once;
  - layers judged by Atlas's own taxonomy (`atlas.claims.predicates.LAYERS`).
- **The conformance check's known answers failed before the runs.** Recall at 10 was 0.08, at 50 0.12. The owner chose to run anyway, and this report says so. That check recalls at Hindsight's defaults, not at the investigations' settings (pilot fix 40), so it understates what an investigation reaches.
- **Mixed consolidation:** the observations were consolidated partly by qwen3.8 27B on the owner's 5090 and partly by MiniMax-M3 (ticket 21).

## The measures

| | 1 laser chips | 2 InP substrates | 3 module assembly | 4 DSP and drivers | 5 coherent demand | Bar |
|---|---|---|---|---|---|---|
| Precision | 67% (64/95) | 58% (44/76) | 69% (49/71) | 39% (14/36) | 66% (57/86) | ≥ 80% |
| Saved work | 0 | 2 | 0 | 0 | 1 | ≥ 3 |
| Trust gate | fails | fails | fails | holds (no finding) | fails | holds |
| Baseline coverage | 40% | 20% | 30% | 10% | 10% | ≥ 50% |
| Roles ran | yes | yes | yes | yes | yes | yes |
| Tokens | 987,654 | 912,621 | 980,406 | 943,393 | 986,314 | ≤ 2,000,000 |
| Latency | 26.3 min | 22.7 min | 25.0 min | 20.8 min | 21.7 min | ≤ 20 min |
| Researcher's hour on the card | 4/33 | 5/32 | 1/25 | 1/26 | 5/28 | (reported) |

## Saved work

Three findings pass the trust gate and count as saved work:

- **InP export controls.** China put InP substrates on its export control list on 2025-02-04, and all three of Tongmei's substrate families need MOFCOM export permits (AXT's 10-Q of 2026-08-13; investigation 2).
- **Lumentum's allocation.** "This demand is outpacing our current supply which has required us to make decisions on supply allocation", with substrates from Chinese suppliers and its UK fab "generally a safe harbor" (investigation 2).
- **Ciena's demand.** Ciena expects "demand outstripping supply" into 2027 and is "effectively double our CapEx intensity specifically this year to increase supply capacity" (investigation 5).

## Unsupported or wrong

- **The trust gate.** The Editor states agreements, plans and development as present fact. AXT's development-and-supply agreement with Coherent turns into present supply in three runs. It also turns a conditional into manufacture, qualification in progress into volume production, and "two to three months" into "one to three".
- **The Claims.** Hedged, conditional or development language becomes `sole_sources`, `qualified_for`, `manufactures`, `capacity_constrained` or `expands_capacity_for`. `owns` is read from an investment or a warrant with the direction reversed. Another market's sentences (consumer VCSELs, industrial lasers) and risk-factor boilerplate are taken as on the question.

## Missed evidence and the baseline

The cards miss the most on-question content of the seeds' own filings and calls:

- AXT's export-permit status: no US InP permits through August 2026, and a backlog of orders waiting.
- Coherent's DCI demand and its assembly build-out.
- Applied Optoelectronics' capacity and qualification.
- MACOM's view of the DSP-to-LPO shift.
- The magnitudes: 3X InP capacity, doubling by year-end, units per month.

A plain BM25 search of the archive surfaces half or more of these in its top ten. The cards cover 11 of the 50 on-question hits judged.

## The roles

- **Skeptic:** read documents with passages in every run.
- **Financial Analyst:** sourced an input for every seed with as-of figures in every run.
- **Editor:** wrote open questions in every run.
- **Scout:**
  - investigation 1 kept SEO market-report pages;
  - investigation 2 only SEC full-text hits;
  - investigation 3 only commentary;
  - investigation 4 three leads in all;
  - investigation 5 sent one query of ten at the question's subject.
- **Memory's pointers:** sent Investigators to the theme's laser makers whatever the question's layer.

## Cost and latency

- **Cost:** 4,810,388 MiniMax tokens for the five, inside the cost bar in every run.
- **Latency:** 21 to 26 minutes, every run over the 20-minute bar. The role calls run one after another (pilot fix 27).

## The §15 demo

Not re-run for this verdict (pilot-review ticket 12, open). Publishing needs approved edges, and those exist now. The replay item needs a local replay Hindsight.

## The evaluation

- **Scripted (CI):** every gold case passes in the scripted mode (`tests/integration/test_evaluations.py::test_every_gold_case_passes_in_fake_mode_and_the_run_is_stored_and_served`, in the suite below).
- **Live:** the live run (pilot-review ticket 11) has not been made; it waits on the owner's adjudication of the gold cases and spends MiniMax.

## Test status

- **The release:** the `v0.4.6` release run (37457705406) succeeded.
- **Main:** CI on main is green on 2026-10-07 under the staged pipeline (run 37616875088): the static stage (ruff, pyright, 109 frontend unit tests), then the suite (1,699 pytest tests, 16 e2e tests, and the image build and smoke).

## The edges

Ticket 09's rule was applied by the lead after the fifth run. Of the 233 Relationships with Evidence from the five runs:

- 87 approved (every Evidence Claim right);
- 29 rejected (every one wrong);
- 100 left (mixed, off-question, or with earlier Evidence not reviewed here);
- 17 already decided before.

## Defects, by how many investigations each hurt

| Ticket | Defect | Investigations |
|---|---|---|
| 37 | The Scout keeps weak or one-channel leads | 5 |
| 34 | The Editor states agreements, plans and development as present fact (trust gate) | 4 |
| 35 | Hedged, conditional and development language becomes a positive Claim | 4 |
| 36 | The reading follows the theme's strongest story, not the question | 3–4 |
| 38 | The Claim model can't hold a magnitude, a share or a regulatory status | 3 |
| 39 | `owns` from an investment or a warrant, reversed | 3 |
| 33 | The grounding check drops faithful findings on punctuation and labels | 2 (a whole card in one) |
| 27 | Role calls run one after another (latency) | 5 |
| 40 | The conformance check recalls unlike investigations; the recall cap unmeasured | (tooling) |

## The next effort

**Not decided here: pilot-review ticket 13, with the owner.** The evidence points at the reading and the expressiveness, not the trust machinery. The lead's proposal for that conversation has three parts:

- **Reading by an agent** with web access and the archive, as in the researcher's hour.
- **Trust by Atlas's ledger:** every proposed fact's source archived through the fetch gate and its quote checked verbatim, with a Claim model that holds figures, shares, dates and regulatory status.
- **Hindsight as memory over time:** prior findings, contradictions, what changed. It would no longer be the index that decides what to read.

A cheap first test needs no new code: run the researchers' cited sources through the archive and the verbatim span check, and count what survives. Two things wait until after the design question:

- **The held-out answer key:** Serenity's flagged names and dates (ticket 02, 2026-10-03), which the owner provides.
- **The mechanical fixes (33, 39, 40):** they are cheap and fit any design.
