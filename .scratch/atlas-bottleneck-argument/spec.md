# Spec (draft): The bottleneck argument

**Status:** in progress (the pilot's verdict on 2026-10-07 was fail; the owner gave the lead free rein to fix it the same day, so this spec is the next effort: items 8 and 9 come from the verdict, and the build starts with them; the reading-agent tickets are in `.scratch/atlas-bottleneck-argument/issues/`)

This file is where feedback about what Atlas lacks as an investment research product is kept, so it is not scattered across log entries and chat. Each source is dated; each requirement says which source asked for it. Add to "Feedback received" first, then fold it into the sections below.

## Feedback received

| Date | From | What it said | Where it went |
|---|---|---|---|
| 2026-10-02 | The owner | The outcome: take the Serenity method and automate it with LLMs, research and memory, "to identify where the bottle necks are and if the evidence is there, make financial bets on it". The lead guides scope and keeps the project in line with that ambition; the lead runs the review loop; the owner wants evidence at the final decision. | Problem Statement; the pilot-review map's scope rule |
| 2026-10-02 | The lead (asked by the owner for a view of the whole project) | The method and the discipline are better than the output, which is the right way round. Risks: the surface area for one owner; the owner's review queue; the judges and the system are the same model family; the real comparison is the owner's hour with a search box and a chat model. | The verdict criteria's "researcher's hour" comparison; the scope rule |
| 2026-10-02 | Codex, first review | Sound architecture (archive, Assertions and Memory kept apart); real progress on investigation 1 (precision 60% to 84.6%, coverage 20% to 50%, AXT found) at ten times the tokens; the synthesis can exceed its evidence; disconfirmation coverage incomplete; the research advantage needs broader proof. Three engineering defects. | Pilot-fix tickets 29 (ships with the memory-quality release), 30, 31; ticket 25's disclosure into the release |
| 2026-10-02 | Codex, second review ("what are we lacking") | Organise the research around proving or disproving a bottleneck and who captures its economics: a structured argument; the next action chosen by the most consequential uncertainty; meaning checked where a finding becomes a conclusion; economic capture; disconfirmation per premise; a prospective learning loop. | This spec |
| 2026-10-04 | Codex, roadmap review; the owner asked to commit it for Claude's later planning | Separate backlog completion from product preparation; prototype one dossier during consolidation; move scenario metric/period correctness forward; retain the frozen five-case verdict; then deliver the argument, economic capture/market expectations and prospective predictions. These sequencing changes remain proposed. | [Preserved roadmap and ticket dispositions](../../docs/research/proposed-roadmap-2026-10-04.md); reconcile with the pilot map when planning resumes |
| 2026-10-07 | The pilot's verdict on 0.4.6 (`docs/pilot-report.md`) | **Fail.** No investigation meets the bar; the trust gate fails in four of five. A researcher's hour (one agent, web search and the archive's term search) found 144 true, cited facts; the cards had 16, and every saved-work finding of the cards was in the researchers' answers. What holds: every quote verbatim at its archived span, reviewers agree (kappa 0.77–0.86). What fails is the reading (what is read: Memory's pointers and the Scout's queries follow the theme's strongest story, not the question; the Scout's leads are SEO pages or one channel) and the expressiveness (a Claim can't hold a figure, a share, a date or a regulatory status, which are most of the researchers' facts). The researchers drew mostly on call transcripts and filings, which Atlas already archives. The owner, the same day: "do what you can to fix this. Free rein." | Solution items 8 and 9; this spec becomes the next effort (pilot-review ticket 13) |
| 2026-10-06 | The owner (frontend session) | "Atlas's job is to help with finding bottlenecks: come up with a thesis and then provide evidence for the thesis. The website is where we present this. We want this as automated as we can with LLMs on the Atlas side; on the frontend we present findings to an end user who wants to understand and consume the thesis." On the Company dossier as built: "a nightmare to navigate and understand"; the end user looks for the direction the research found and the evidence for Atlas's assessment, not raw data. The glossary's term stays: a Hypothesis, headed by its Thesis Statement. | Solution item 7; User Stories (the reader); open question: how much of the publish gate stays manual; the reader page is prototyped in `.scratch/atlas-frontend/` (ticket 08) as this spec's design input |

## Problem Statement

The owner wants to know, for a supply-chain bottleneck, whether to put money on it. Atlas today answers with a research card: a list of findings, each resting on real quotes. A researcher still has to assemble the argument: what exactly is constrained and for how long, whether a second source or substitute is coming, who holds the scarce capability, how the scarcity reaches that company's revenue or margin, and what would prove it wrong. The card does not say which of those steps is established and which is missing, so an attractive story resting on one unsupported step reads as complete. Its findings can also say more than their quotes (investigation 1 on 0.3.1: two of eleven findings fully supported), and "no contradiction found" does not say what was challenged.

## Solution

For one bottleneck, Atlas produces a short, defensible answer to: **what must be true for this company to benefit, which parts have we established, and what should we investigate next?** The bet stays the owner's decision, outside Atlas (product spec §1.4).

1. **A structured argument** in place of free-text findings: the steps below, each with its supporting Evidence, its counterevidence and a status (supported, disputed, unknown). (Codex, second review, 1)
2. **Research directed by the weakest consequential step:** after each pass, a few unresolved steps, how each could change the argument, and one bounded action to resolve the most consequential. Simple rules first. (Codex 2, 2)
3. **Meaning preserved from Claim to conclusion:** each step's statement keeps the actor, direction, tense (reported, expected, asked by an analyst, inferred by Atlas) and certainty of its Evidence; an inference names its premises; a check with its own evaluation cases. (Codex 2, 3; Codex 1)
4. **Economic capture made explicit:** pricing arrangements, customer bargaining power, capacity cost, qualification time, financing and dilution, duration; the scenario separates incremental exposure from the existing business and names the assumption that drives the result. Market expectations come after the causal argument. (Codex 2, 4)
5. **Disconfirmation per step,** on the same companies and horizon as the support: new entrants, qualification progress, substitutes, inventory, cancellations, capacity additions; each step shows what was challenged, which sources were examined and what remains unchecked. (Codex 2, 5; Codex 1)
6. **A prospective loop:** predictions with a measure, a deadline, an expected range and a source that settles them, operational first (capacity online, qualification, lead times, margins, financing); rejected Hypotheses recorded too. (Codex 2, 6; product spec §9)

7. **The website presents the argument to a reader** who wants to understand and consume the thesis: the Thesis Statement first, then the steps with their status, evidence and counterevidence, records one click deeper; producing it is automated on Atlas's side as far as possible. Open question for this effort: how much of the publish gate (the owner's approval of every edge a version rests on) stays manual. (The owner, 2026-10-06)

8. **Reading directed by the argument, not by the theme** (the verdict, 2026-10-07): a reading agent works the argument's steps for the question; for each step it searches where a researcher would (the seeds' and the universe's archived filings and call transcripts by term search, Memory recall, and later the web), reads the passages it chooses, and records facts. Its budget is spent on the step that is weakest, not on the theme's strongest story. Memory serves what was established before (prior facts, contradictions, what changed), not as the only index of what to read.

9. **Facts that hold what a researcher needs** (the verdict): a fact is a verbatim quote at an archived span with its company, the argument step it bears on, and, when the quote states them, a quantity (value, unit, metric), a period or date, and a status (in effect, planned, under development, hedged, regulatory). The span check (every quote verbatim at its archived span) stays the trust gate's first half; a finding's statement is checked against its facts' quotes for meaning (item 3) before it reaches a card. Typed edges (the Relationships) stay for the predicates they serve; a fact needs no predicate.

The steps of the argument (Codex 2, 1; the Serenity method's bottleneck test, `docs/research/serenity-skills-alignment.md` on its branch, M1 to M6):
- what is constrained, in what units, over what period;
- the evidence that demand exceeds qualified supply;
- how quickly capacity, another supplier or a substitute can relieve it;
- who controls the scarce capability;
- how that company captures more revenue or profit (share of the bill of materials, pricing power, financing);
- the observation that would invalidate the argument.

## User Stories

To be written by `/to-spec` after the verdict, from the workflow the verdict names. One is given already (the owner, 2026-10-06):
- As a reader of Atlas's research, I want to open a Hypothesis and understand its thesis, the argument's steps with the evidence and counterevidence behind each, and how sure Atlas is, without reading raw records, so that I can judge the thesis myself. The records (spans, sources, memory) are one click deeper, never the first thing shown. **Design input:** the reader page the owner chose on 2026-10-06, `.scratch/atlas-frontend/issues/08-hypothesis-reader-prototype.md` (variant A, the argument as rows; code on the branch `prototype/thesis-reader`), with what the data must give it. **Exposures:** after the argument, the page shows who is positioned: each Exposure (`CONTEXT.md`) tested on the Serenity method's six company tests, evidence for, against or unknown, ordered by an evidence count that is not a rating, and a closing line naming tests no company has evidence for (`.scratch/atlas-frontend/issues/11-who-is-positioned.md`). This is item 4 (economic capture) as a reader sees it. **Review state for a reader** (the owner asked, 2026-10-06, who "Awaiting review" waits on: the lead's review loop, not the owner): the reader page should say "Not yet verified" rather than name a queue, and whether that review stays manual is the publish-gate question above.

## Implementation Decisions

Not decided. What is known now:
- The Hypothesis model already has mechanism fields (`backend/atlas/hypotheses/model.py`, demand, possible constraint, economic capture) as text: the argument extends them, it does not start over.
- The evaluation cases for item 3 are being collected now at no cost: each verdict run's review keeps its wrong Claims and misstated findings with the reason (`.claude/skills/pilot-review/SKILL.md`).
- The memory-quality release ships the first piece of item 5: the card states, per company, whether the Skeptic checked it (pilot-fix ticket 25, split).

## Out of Scope

- Anything before the verdict (the pilot-review map's scope rule).
- Trading orders, sizing or execution (product spec §1.4).

## Further Notes

- The verdict decides which bottleneck workflow saves the owner work; this argument is built on that one, not on all five questions at once.
