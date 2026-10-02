# Spec (draft): The bottleneck argument

**Status:** needs-triage (a draft held until the pilot's verdict, pilot-review ticket 13, which confirms, narrows or replaces it; then `/to-spec` finishes it and `/to-tickets` breaks it down)

This file is where feedback about what Atlas lacks as an investment research product is kept, so it is not scattered across log entries and chat. Each source is dated; each requirement says which source asked for it. Add to "Feedback received" first, then fold it into the sections below.

## Feedback received

| Date | From | What it said | Where it went |
|---|---|---|---|
| 2026-10-02 | The owner | The outcome: take the Serenity method and automate it with LLMs, research and memory, "to identify where the bottle necks are and if the evidence is there, make financial bets on it". The lead guides scope and keeps the project in line with that ambition; the lead runs the review loop; the owner wants evidence at the final decision. | Problem Statement; the pilot-review map's scope rule |
| 2026-10-02 | The lead (asked by the owner for a view of the whole project) | The method and the discipline are better than the output, which is the right way round. Risks: the surface area for one owner; the owner's review queue; the judges and the system are the same model family; the real comparison is the owner's hour with a search box and a chat model. | The verdict criteria's "researcher's hour" comparison; the scope rule |
| 2026-10-02 | Codex, first review | Sound architecture (archive, Assertions and Memory kept apart); real progress on investigation 1 (precision 60% to 84.6%, coverage 20% to 50%, AXT found) at ten times the tokens; the synthesis can exceed its evidence; disconfirmation coverage incomplete; the research advantage needs broader proof. Three engineering defects. | Pilot-fix tickets 29 (ships with the memory-quality release), 30, 31; ticket 25's disclosure into the release |
| 2026-10-02 | Codex, second review ("what are we lacking") | Organise the research around proving or disproving a bottleneck and who captures its economics: a structured argument; the next action chosen by the most consequential uncertainty; meaning checked where a finding becomes a conclusion; economic capture; disconfirmation per premise; a prospective learning loop. | This spec |

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

The steps of the argument (Codex 2, 1; the Serenity method's bottleneck test, `docs/research/serenity-skills-alignment.md` on its branch, M1 to M6):
- what is constrained, in what units, over what period;
- the evidence that demand exceeds qualified supply;
- how quickly capacity, another supplier or a substitute can relieve it;
- who controls the scarce capability;
- how that company captures more revenue or profit (share of the bill of materials, pricing power, financing);
- the observation that would invalidate the argument.

## User Stories

To be written by `/to-spec` after the verdict, from the workflow the verdict names.

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
