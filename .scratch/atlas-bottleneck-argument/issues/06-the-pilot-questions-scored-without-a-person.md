# 06: The pilot questions scored without a person, before a review

**Status:** ready-for-agent
**Type:** task

**What to build:** `.scratch/tools/pilot_score.py <folder> <n>`, the lead's tool that scores a saved investigation (as `pilot_runs.py` saves it) against what the 2026-10-07 verdict established, without a reviewer, so a change can be compared run against run before a human review:

- **baseline coverage, automatic:** for each of the question's on-question baseline hits judged on 2026-10-07 (`.scratch/live-runs/pilot-0.4.6/inv-<n>/review/workflow-result.json`, `baseline.hits`), whether an accepted Claim's or a Fact's quote overlaps the hit's passage (or one of its `also_in` documents' same paragraph);
- **the researcher's facts, judged:** each of the researcher's hour's cited facts for the question (`answer.facts` in the same file) against the new card and its Claims or Facts, by one MiniMax judge call per batch of ten (on the card or not), reported with the count;
- tokens, role calls and wall time.

It prints one table comparing the new run with the 0.4.6 run of the same question.

**Acceptance:**
- [ ] The tool, its judge prompt in `.scratch/tools/` (not a product role); runs on the five saved 0.4.6 runs and reproduces their baseline coverage within one hit of the reviewers' marks (report the agreement).

## Result (implementer)

Built `.scratch/tools/pilot_score.py` and `pilot_score_judge.md`. The agreement box is left unticked. Automatic baseline coverage on the five saved 0.4.6 runs (an accepted Claim overlapping the hit's span, or sharing an 8-word run in the hit's document or an `also_in` document) gives 2, 2, 2, 1, 0 of ten hits; the reviewers' strict "covered" marks are 4, 2, 3, 1, 1. Questions 2 to 5 are within one hit; question 1 is two short, because the reviewers also marked two hits covered by a Claim that restates the passage in another document (a semantic call). A content-word containment rule was tried and removed: it added false positives in questions 2 and 3 and fixed nothing in question 1. `--judge` was tested only against a local stub, never live. `python .scratch/tools/pilot_score.py --agreement` prints the agreement.
