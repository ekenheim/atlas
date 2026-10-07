# 33: The grounding check drops faithful findings on punctuation, citation labels and nested quotes

**Status:** ready-for-agent
**Hurt:** investigations 4 (the whole card: 14 of 14 findings dropped) and 5 (Coherent's InP-constraint finding), verdict runs on 0.4.6.

`atlas.investigations.grounding.ungrounded` matches a finding's quoted phrases as exact substrings and reads tokens like `c10` as numbers. Investigation 4 (`995b8fb3-e87b-44ae-84ed-ff24bcac90fb`) lost every finding though each cited accepted Claims and quoted them faithfully:

- a quoted phrase ending in a comma inside the quotation marks ("…highly capable TIAs and drivers,") where the Claim's quote (`19dc06d0`) ends "drivers.";
- the Editor's citation labels written into the statement ("(c10, c15)"), reported as ungrounded figures;
- nested quotes: the quote has `("TSMC")` (`33c3d5c9`), the Editor wrote `('TSMC')`.

**Acceptance:** trailing punctuation inside a quoted phrase, the Editor's own claim labels and the kind of a nested quotation mark no longer make a finding ungrounded; investigation 4's 14 dropped statements (`.scratch/live-runs/pilot-0.4.6/inv-4/review/card.json`, `unsupported_findings`) pass as regression cases; a changed name, figure or phrase still fails. The trust gate's misstatements (ticket 34) are not this check's to catch.
