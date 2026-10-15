# 25: The judge knows a transcript quote's speaker; the draft's rewrites keep the draft's rules

Type: build
Status: in-review
Blocked by: none

## Why

The Editor re-run on 0.6.5 (2026-10-15, session `3ef0854d`, Hypothesis `0f656e66`, run `b8417cee`) kept the constraint step's statement (the v2 prompt works for steps) but:
- The thesis and the control step were judged misstated because "the quotes do not identify the speaker as AXT's VP of business development". A transcript quote's speaker is in its paragraph's label ("Name (Title, Firm)", `atlas.claims.speakers`), which the judge is never shown; the two blind Fact reviewers of the MCP session judged the same attribution right from the label. Every judged statement about a call or conference transcript is exposed to this.
- The stored thesis came from the rewrite call, which still runs as the shared `editor` role on MiniMax with `editor-revise.v2` and does not know v2's rules: it strung the Facts together with quotation marks. (The draft itself ran as `hypothesis_editor` on chatgpt, prompt v2; routing works.)

## What to build

- **The speaker beside each quote.** Wherever the finding judge is sent a cited quote (`atlas.investigations.meaning` / the judge request's quoted items, and the grounding check's grounds), a transcript quote carries its speaker as the paragraph label gives it (name, title, firm; `atlas.claims.speakers`), as metadata the judge may use for attribution and grounding may use for names, never as quoted text. A filing quote carries none. Every caller benefits (card findings, argument statements, `/statements/judge`, ticket 23's judges, the Belief draft).
- **Measured before shipping.** The change alters the v4 judge request for transcript quotes, so run `.scratch/tools/finding_judge_eval.py --argument` (the 130 labelled statements; one vote; on the judge's model, `chatgpt`) before and after, and report caught/flagged both ways in the log and `docs/experiments.md`: ship only if caught does not fall and flagged does not rise by more than one. The lead runs the live measurement; the implementer adds whatever the tool needs to send the speaker (its labelled data carries the source version ids and spans).
- **The draft's rewrites keep the draft's rules.** In `atlas.hypotheses.belief_drafting`, the reground and revise calls run under the `hypothesis_editor` role name (routed with it), and their request says the draft's rules (statements and thesis in the Editor's own words, no quotation marks, no qualifier beyond the quotes, a thesis states what may be true). New prompt files if a prompt changes (never edit a released one).

## Acceptance criteria

- [x] HTTP-seam tests: a judge request for a statement citing a transcript Fact carries the speaker label (name, title, firm), one citing a filing Fact carries none; grounding accepts a speaker's title from the label; a Belief draft's revise call is recorded as `hypothesis_editor` and its stored thesis has no quotation marks when the scripted rewrite has none.
- [x] The judge measured before and after on the 130 labelled statements, the numbers in `docs/experiments.md` (the lead).
- [ ] The Editor re-run on production after deploy keeps both proven Beliefs' steps and a judged thesis (the lead).
