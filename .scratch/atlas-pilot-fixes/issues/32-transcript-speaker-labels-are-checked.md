# 32: A transcript's speaker labels are checked before the own-speaker rule trusts them

**What to build:** A TradingView transcript whose speaker labels are visibly wrong is detected at parse or at Claim time, so a quote is never attributed to the wrong person, and a transcription substitution inside a quote is not stored as the company's words.

Evidence (2026-10-04, read by the lead while making `docs/research/early-signal-case-studies.md`):

- **AXT, Q3 2025 call (in the archive, provider `tradingview`, available 2025-10-30).** Paragraphs 11–17 are the CEO's prepared remarks (the CFO hands over to "Dr. Morris Young", and the section ends "I will turn the call back to Gary") but every one is labelled `Gary Fischer (CFO, AXT)`. In the same paragraphs the words "gallium arsenide" are printed as "Gary Fischer": "The receipt of Indium Phosphide and Gary Fischer export permits remains the single most significant gating factor".
- **SanDisk, Investor Day 2025-02-11 (read ad hoc, not in the archive).** Every paragraph of the first speakers, the CEO's and CFO's sections included, is labelled `Ivan Donaldson (VP of Investor Relations, SanDisk)`.

Why it matters: the own-speaker rule (`atlas.claims.speakers`, pilot-fix ticket 22) accepts a quote when its paragraph's label names the filer. Both mislabels name a company officer, so the rule passes and the accepted Claim records the wrong `speaker`; and a quote from AXT's paragraphs would carry "Gary Fischer export permits" as the company's verbatim words, span-checked against a text that is itself wrong.

- A paragraph whose text hands over to, or is addressed by, another named participant than its label is flagged (`speaker_label_suspect`), and a Claim from it records the flag; the Evidence tray shows it.
- A person's name standing where the sentence needs a noun phrase (the name of a call participant directly before a common noun, as in "Gary Fischer export permits") is flagged the same way.
- Count the flags per transcript in the version's metadata, so the share of suspect transcripts in the archive can be read before deciding anything stronger (re-fetch, another provider, an audio-free check against the company's own published transcript).

**Blocked by:** None

**Status:** needs-triage after the verdict; not a blocker (the rule still rejects analysts, and no accepted Claim from the two paragraphs is known). First measure how many archived transcripts are affected.
