# 07: An optional role failing doesn't sink the card

**Status:** done (8 October; awaiting CI and release)
**Type:** bug

**What happened:** pilot question 2 on 0.5.3, argument plan (investigation `f8161b4c-…`, 2026-10-07): Scout, six Readers and the Skeptic succeeded (188 Facts, 73% right on review), the Financial Analyst failed after 3 attempts, and the investigation stopped `needs_review` with the Editor cancelled, so there is no card at all. The rule is `atlas.investigations.tasks` (a task's last failed attempt calls `stop(..., "needs_review")`), right for a Reader or the Editor, wrong for a role whose output the card can do without.

The analyst's failures: attempt 1 cut off at its 4,096-token output cap; attempts 2 and 3, each repaired once, still wrote an input's `kind` as `"assertion"` (then `"assertion_id"`) where only `sourced | estimated | missing` is allowed (the other errors were repaired).

**What to build:**
- On its last attempt, a failed Financial Analyst (in both plans) is recorded `failed` with its error and the plan advances; the Editor runs without its proposal and the card says the analyst failed and why (one line, in the card's limits). Any other role keeps today's rule.
- The analyst's answer is normalized before validation the way the Reader's is (`atlas.roles.reader`, `_as_the_model_writes_it`): an input whose `kind` names an Assertion or observation (`assertion`, `assertion_id`, `observation`, `observation_id`) with that id given is `sourced`; one without an id is `missing`.
- The analyst's output cap as the Reader's (6,144), cut-off answers asked again once with the cap doubled like the Editor's.

**Acceptance:**
- [ ] An integration test: an argument investigation whose analyst fails every attempt ends with an Editor card and the analyst's failure on it.
- [ ] A unit test of the normalization over the two recorded answers' shapes (`kind: "assertion"` and `kind: "assertion_id"`).
- [ ] Questions 1 and 3's runs, where the analyst succeeded, are unchanged (the stop rule only).

## Result (lead)

Built as specified, except that the failed Analyst is recorded `skipped`, with the reason and `analyst_failed: true` in its artifacts, rather than `failed`: `skipped` is already a finished state the plan advances past. The card has no section for the Analyst; its task shows the reason on the investigation page. Rules in docs/decisions.md, 2026-10-08.
