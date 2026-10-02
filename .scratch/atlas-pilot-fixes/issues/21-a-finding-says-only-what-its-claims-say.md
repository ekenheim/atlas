# 21: A finding says only what its Claims say

**What to build:** Every sentence of a research card's finding is held to the quotes of the Claims that finding cites. A figure, a date or a name that none of its cited quotes contains does not reach the card as part of a finding.

The pilot's trust gate, second half ("every finding on the card cites Claims that say what the finding says"): a failure is a blocker. Evidence: production 0.3.1, investigation `452c3b9d-2e2f-4cc6-bc54-5130155b9aac` (pilot investigation 1, fifth run; reviewed in `.scratch/pilot/results.md`, "Investigation 1, fourth and fifth runs"); Editor role call `2ea4071f` (`editor.v6`). Nine of the eleven findings state something no cited Claim says and five misstate one. The lead traced each addition in the saved run:
- **bear context written into findings:** "$600.1 million net" (finding 6), "£81m fundraise" and "332,183,678 new ordinary shares" (finding 8), "a shortfall payment obligation" (finding 7): all in the Skeptic's bear-context items the Editor is sent, none in a cited Claim;
- **a lead's text in a finding:** "Järfälla, Sweden" (finding 1) occurs only in a kept web lead's title (Tier C);
- **another finding's Claim:** "Zurich" (finding 1) is in a quote only finding 2 cites;
- **the Editor's own errors:** "Covert is Coherent's laser customer for NVIDIA" (finding 3; the word occurs nowhere), "vertically integrated" in InP where the quote says garnet (finding 4), "200G-per-lane" added to a design-win quote (finding 9), two agreements with two companies written as one (finding 7).

- **The prompt (`editor.v7`):** a finding's statement may say only what the quotes of the Claims it cites say; bear context and contradictions are written in their own sections of the card and may be named in a finding's limitations, never in its statement; a lead is never a source for a statement; a quoted phrase must be quoted from a cited Claim.
- **The check, in code, after the Editor answers:** for each finding, every number (amounts, counts, percentages, years and dates) and every capitalised name in the statement must occur in the quote, subject or object of a Claim that finding cites (after the typographic fold the quote rule uses; a company's display name and legal name count as the same name; the question's own words are allowed). What is not found is the finding's `ungrounded` list.
- **What happens to an ungrounded finding:** the Editor is asked once more for that finding with its ungrounded terms named (one call for all such findings, inside the run's budget); a finding still ungrounded is kept on the card under `unsupported_findings` with the reason `ungrounded: <terms>`, like a finding citing no Claim today, and is no longer a finding.
- The card's read shows each finding's check (`grounded: true`); the investigation page marks nothing new for a grounded finding.
- `docs/decisions.md`: "A finding says only what its Claims say" (what is checked, what is not: the check holds names and figures, not the logic of a sentence; that stays the reviewer's).

**Blocked by:** None

**Status:** ready-for-agent

- [ ] Integration test at the investigation seam with the scripted LiteLLM fake: an Editor answer whose finding carries a figure found only in bear context and a name found only in a lead is asked again once with those terms; the repaired finding stands; an unrepaired one is listed under `unsupported_findings` with `ungrounded: ...` and is not a finding.
- [ ] A finding whose every number and name is in its cited Claims passes without a second call (the existing tests' findings unchanged).
- [ ] A name written as the display name where the quote has the legal name is grounded; a year in the question is allowed; the fold handles typographic quotes and hyphens.
- [ ] Unit tests of the grounding function: amounts with currency signs and separators, percentages, dates, multi-word names.
- [ ] The evaluation cases (fake mode) pass; decision entry; `AGENTS.md` line; API client regenerated if the read changes.
