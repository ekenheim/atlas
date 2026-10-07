# 04: Findings checked for meaning against their quotes

**Status:** done (implementer; box 2 is the lead's live run of `.scratch/tools/finding_judge_eval.py`; box 3's end-to-end test is written and awaits the runners)
**Type:** task

**What to build:** the trust gate's second half as a check, not a review: before a finding (a research card's finding today, an argument step's statement after ticket 05) is kept, a judge role compares it with the quotes it cites and answers, per finding, `supported` or `misstated` with the words that go beyond the quotes. A misstated finding is rewritten once by the Editor with the judge's reason, judged again, and dropped (kept in `unsupported_findings` with the reason) if still misstated. The deterministic grounding check (`atlas.investigations.grounding`, pilot fix 33) runs first.

The judge checks what the grounding check doesn't (its `grounding_limit`): tense and status (an agreement, plan, development, qualification in progress or hedge stated as present fact), direction (who supplies, owns or buys from whom), figures and dates as quoted ("two to three months" is not "one to three months"), and two facts merged into one claim neither quote makes.

Why: the trust gate failed in four of five verdict investigations, every time on such wording (pilot fix 34).

**Acceptance:**
- [x] `atlas.roles.finding_judge` with prompt `finding_judge.v1.md`, called by the Editor's task on every finding; its verdicts recorded on the card (`judged`, with the reasons).
- [x] Measured on the verdict's labelled findings (`.scratch/live-runs/pilot-0.4.6/labeled-findings.json`, not in git: 18 findings, 9 failing the trust gate with the reviewers' misstatements): report how many misstated findings the judge catches and how many supported ones it wrongly flags, on the owner's MiniMax (at most 40 calls; the lead runs it). Target: catch at least 8 of 9, flag at most 1 of 9 supported.
- [ ] Tests with the scripted fake: a misstated finding rewritten and accepted, one dropped after the rewrite, a supported one kept. (Written: `tests/integration/test_investigations.py::test_a_misstated_finding_is_rewritten_once_then_kept_or_dropped_and_a_supported_one_kept`, scripted LiteLLM fake, for the runners; `tests/unit/test_finding_meaning.py`, 6 passed locally.)

## Comments

**2026-10-07, the lead: measured live on MiniMax** (`.scratch/tools/finding_judge_eval.py`, 18 calls a run, reports under `.scratch/live-runs/*-finding-judge-eval/`):

| Judge | Misstated caught | Supported flagged |
|---|---|---|
| `finding_judge.v1`, one vote | 9 of 9 | 5 of 9 |
| `finding_judge.v2`, one vote (run 1) | 9 of 9 | 3 of 9 |
| `finding_judge.v2`, one vote (run 2) | 8 of 9 | 2 of 9 |
| `finding_judge.v2`, **two votes, misstated only when both say so** | **8 of 9** | **1 of 9** |

v1 flagged attribution of a company's own call ("Lumentum says"), a list grouped differently and a word for a subsidiary; v2 adds a materiality rule and says a Claim's subject and source settle who said it. The flags that remained were different each run (one vote errs strictly at random), so the judge votes twice (`ATLAS_FINDING_JUDGE_VOTES`, default 2; `atlas.investigations.meaning.voting`): the target is met. The one supported finding both votes flagged (Coherent's 6-inch capacity, investigation 2) is flagged for leaving out a yield qualifier and moving a phrase into quotation marks, borderline; the rewrite step would correct it rather than drop it.
