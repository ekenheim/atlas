# 04: Findings checked for meaning against their quotes

**Status:** ready-for-agent
**Type:** task

**What to build:** the trust gate's second half as a check, not a review: before a finding (a research card's finding today, an argument step's statement after ticket 05) is kept, a judge role compares it with the quotes it cites and answers, per finding, `supported` or `misstated` with the words that go beyond the quotes. A misstated finding is rewritten once by the Editor with the judge's reason, judged again, and dropped (kept in `unsupported_findings` with the reason) if still misstated. The deterministic grounding check (`atlas.investigations.grounding`, pilot fix 33) runs first.

The judge checks what the grounding check doesn't (its `grounding_limit`): tense and status (an agreement, plan, development, qualification in progress or hedge stated as present fact), direction (who supplies, owns or buys from whom), figures and dates as quoted ("two to three months" is not "one to three months"), and two facts merged into one claim neither quote makes.

Why: the trust gate failed in four of five verdict investigations, every time on such wording (pilot fix 34).

**Acceptance:**
- [ ] `atlas.roles.finding_judge` with prompt `finding_judge.v1.md`, called by the Editor's task on every finding; its verdicts recorded on the card (`judged`, with the reasons).
- [ ] Measured on the verdict's labelled findings (`.scratch/live-runs/pilot-0.4.6/labeled-findings.json`, not in git: 18 findings, 9 failing the trust gate with the reviewers' misstatements): report how many misstated findings the judge catches and how many supported ones it wrongly flags, on the owner's MiniMax (at most 40 calls; the lead runs it). Target: catch at least 8 of 9, flag at most 1 of 9 supported.
- [ ] Tests with the scripted fake: a misstated finding rewritten and accepted, one dropped after the rewrite, a supported one kept.
