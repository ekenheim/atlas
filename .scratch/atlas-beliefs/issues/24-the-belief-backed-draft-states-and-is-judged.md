# 24: The Belief-backed draft states its Beliefs and is judged whole

Type: build
Status: in-review
Blocked by: none

## Why

The Editor hand run (ticket 16, 2026-10-15, session `b052ebdf`; Hypothesis `5fab64be`, run `385a8782`) drafted from the theme's two proven Beliefs and kept no step statement:
- constraint: the Editor quoted the VP and misquoted him ("received permits in Q3"; the quote says "We did receive permits in Q3"). Grounding refused it, rightly.
- control: the Editor pasted the whole quote as the statement, adding the speaker and "merchant"; the judge called it misstated; the rewrite began "According to the quoted statement, ..." and grounding refused "According" as an ungrounded name (a sentence-initial common word: a grounding defect).
- The thesis says "the merchant market is concentrated in AXT and Sumitomo": "merchant" is in no quote (the same scope word the MCP session's reviewers judged wrong). The thesis is never judged in drafting (ticket 14's deviation 2).

## What to build

- `editor-hypothesis-beliefs.v2.md` (a new file; v1 stays): each step statement states its Beliefs in the Editor's own words, one or two sentences, no quotation marks and no quoted phrases, nothing the Beliefs' quotes do not carry (no scope words such as "merchant", no speaker titles not in the source title), dates as the Beliefs give them; the thesis likewise adds no qualifier its Beliefs lack. `HYPOTHESIS_BELIEFS_EDITOR_PROMPT_VERSION` → v2.
- The role gets its own name for routing (`hypothesis_editor`, not the shared `editor`), so `ATLAS_LLM_ROLE_MODELS` can send it to the judge's model without moving the card Editors; recorded in `docs/decisions.md`.
- The thesis judged in drafting: grounded and judged against the Facts of the Beliefs it cites, like a step statement; a hedge the thesis adds ("may") is not a misstatement (`finding_judge.v5` is told it is judging a thesis and gives the bare hedged proposition no basis; code exempts that clause, not a scope word or an unverifiable basis). A misstated thesis is rewritten once by the reground/revise call; still misstated, the draft is stored with `thesis_judged: misstated` and a gate failure `thesis_misstated` (the owner sees it), not refused.
- Grounding (`atlas.investigations.grounding`): a capitalised word at the start of a sentence or clause that is not a name ("According", "Despite", "Given", ...) is not an ungrounded name; the rule general (a sentence-initial word whose lower-case form is in the grounds or in a short list of discourse words), with unit tests, not one word added.

## Acceptance criteria

- [x] HTTP-seam tests: a v2 draft whose statements carry no quotation marks is kept; a thesis with an unsupported qualifier is judged misstated and lands as the gate failure after one rewrite; a hedged thesis passes; the role routes by its own name; grounding unit tests for sentence-initial discourse words, and that a real unknown name at a sentence start is still flagged.
- [ ] The Editor hand run again on production after deploy: both proven Beliefs' steps keep a statement (the lead).
