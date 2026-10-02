# 25: The Skeptic checks every company the Investigators read

**What to build:** "No contradiction found" on a card means the Skeptic looked. Today it can read nothing of most companies and the card does not say so.

Evidence: production 0.3.1, investigation `452c3b9d-2e2f-4cc6-bc54-5130155b9aac` (pilot investigation 1, fifth run; reviewed in `.scratch/pilot/results.md`, "Investigation 1, fourth and fifth runs"); Skeptic task artifacts: 36 recalls, 3,112 pointers, `documents` 6, `documents_from_pointers` 6, `documents_fallback` true with `documents_from_fallback` 0, `documents_dropped` 121. The six documents are AXT's 10-Q and 8-K and four IQE results documents, all already read by Investigators. Nothing of Lumentum, Coherent, Applied Optoelectronics or MACOM was read: 135 of the 182 accepted Claims went unchecked. Two things combine: the run's document budget was spent by the Investigators (25 of 25), and the Skeptic reads Tier A documents only while the pointers for those four companies lead to transcripts (Tier B). 24 of its 38 accepted items are about IQE, 14 of them its financing.

Decide and build:
- **Its own document budget.** Whether the Skeptic has documents of its own (a setting, as it has its own passage budget) so that the Investigators cannot leave it none.
- **What it may read.** Whether it reads a company's transcripts where the pointers lead (a management statement can limit or date another management statement), keeping the rule that a contradiction's witness is independent of the Claims' Evidence Families; or stays on Tier A and falls back to each unread company's latest 10-K and 10-Q (the fallback that did not fire here).
- **A spread across companies.** A floor of one document per company the accepted Claims name, before any company takes a second.
- **What the card says.** Per company: checked (documents read) or not checked (why). The stop detail and the finding's `needs_review` already distinguish contradicted from not; "not checked" is new.

**Blocked by:** None

**Status:** needs-triage

- [ ] The decision in `docs/decisions.md` ("The Skeptic reads where Memory points" amended), with this run as the evidence.
- [ ] At the investigation seam: with the document budget spent by the Investigators, the Skeptic still reads at least one document of every company the accepted Claims name, or the card lists that company as not checked with the reason.

**2026-10-02, the lead: split, after Codex's review ("'No contradiction found' needs to show exactly what was challenged and what remained unchecked").** The disclosure part ships with the memory-quality release: the research card's `skeptic_coverage` lists, per company the accepted Claims name, the documents and passages the Skeptic read and its outcome (`checked`, or `not_checked` with the reason: no budget left, only Tier B documents pointed, no document), and the stop detail and the investigation page say "not checked" for those companies instead of implying none was found. The rest (its own budget, reading transcripts, the floor per company) still waits for the verdict. The card also states the grounding check's limit (pilot fix 21: names, figures and quoted phrases are checked; direction, tense and the merging of two facts are not).

**2026-10-02, disclosure part built (branch of the disclosure implementer).** Not the whole ticket: the status stays `needs-triage` for the rest (own budget, transcripts, floor per company).

- [x] Disclosure: the card's `skeptic_coverage` (per company the accepted Claims name: `checked` with documents and passages, or `not_checked` with `reason_code` and reason), the stop detail naming unchecked companies, the card's `grounding_limit`, the investigation page's "Skeptic coverage" section; decision entry in `docs/decisions.md` ("No contradiction found" shows what the Skeptic read).
- [x] At the investigation seam: with the document budget spent, the card lists Coherent as not checked (`no_budget`) and the stop detail says so (`test_a_company_the_skeptic_was_left_no_document_for_is_listed_as_not_checked`).
- [ ] The Skeptic's own budget, transcripts and the floor of one document per company (the first acceptance box's decision text is only the disclosure part; the second box's alternative "or the card lists that company as not checked" is met).
