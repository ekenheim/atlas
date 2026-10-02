# 22: An analyst's words are not the company's statement

**What to build:** In a call or conference transcript, a Claim may rest only on words spoken by the company's own people. A quote from an analyst's question is rejected.

Evidence: production 0.3.1, investigation `452c3b9d-2e2f-4cc6-bc54-5130155b9aac` (pilot investigation 1, fifth run; reviewed in `.scratch/pilot/results.md`, "Investigation 1, fourth and fifth runs"). Two accepted Claims rest on analysts' words: Lumentum `expands_capacity_for` Indium phosphide from "you are expanding to Indium phosphide fabs in Japan" (said by a Deutsche Bank analyst; Deutsche Bank 2026 Technology Conference), and Lumentum `expands_capacity_for` indium phosphide capacity from "Maybe I'll start off on the indium phosphide capacity ramp, and just to clarify what you said in your prepared remarks..." (a JP Morgan analyst; Q2 2026 call). The transcript parser (`tradingview-transcript-v1`) writes one line per paragraph with its speaker label, for example "Michael Hurlston (President and CEO, Lumentum Holdings Inc):".

- For a Source Version of source type `transcript`, the Claim check finds the speaker of the quote: the label of the paragraph the quote starts in. A quote that crosses paragraphs of two speakers is rejected (`speaker_mixed`).
- The speaker is the company's when the label's affiliation names the filer (its display or legal name, by the name matcher the party check uses); a label with another firm, or with "Analyst", is not (`analyst_speaking`). A paragraph with no label, or a label without an affiliation, is `speaker_unknown` and rejected: the transcripts on production carry affiliations.
- The Claim record keeps the speaker label of an accepted transcript Claim; the Evidence tray shows it.
- The Skeptic's counterevidence follows the same rule when it reads a transcript (it does not today; the rule is in one place).
- `docs/decisions.md`, "Claim checks": the speaker rule. The Investigator's prompt says that an analyst's question is context, not a statement by the company.

**Blocked by:** None

**Status:** ready-for-agent

- [ ] Integration test at the `extract_claims` seam with the synthetic TradingView fixture: a quote in a management paragraph is accepted with its speaker; the same wording in an analyst's paragraph is rejected `analyst_speaking`; a quote spanning both is rejected `speaker_mixed`.
- [ ] A filing's Claim is untouched (no speaker).
- [ ] The Evidence tray shows the speaker (API client regenerated; frontend unit test of the pure part if one exists for the tray).
- [ ] Decision entry; `AGENTS.md` line; the prompt version bumped and its tests updated.
