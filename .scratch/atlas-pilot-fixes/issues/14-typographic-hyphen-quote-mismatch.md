# 14: A typographic character in the parsed text makes a correct quote mismatch

**What to build:** In investigation 1 on 0.2.5 (`ead2b86e-3556-42ba-9f3e-08660a938f98`, extraction `be086921-ee92-41c2-a715-90840b24595e`), two Claims quoting Coherent's EX-99.2 slides (Source Version `d42626ca-70b8-47e8-9284-0bc1493070d8`) were rejected `quote_mismatch`: the parsed text reads "year‑end", "6‑inch" and "3‑inch" with a non-breaking hyphen (U+2011), and the model wrote ASCII hyphens. The quote is otherwise exact. A third `quote_mismatch` in the same run (version `a0b16b07-7d5d-42a2-adcc-d82c657e375b`, "we remain focused on ramping our capital investment…") should be checked for the same cause.

Locate a quote through a character fold that maps typographic variants to one form (hyphens U+2010 to U+2015 and U+2212, curly and straight quotes, non-breaking and narrow spaces), one character to one character so offsets hold, and record the span and the quote **as the parsed text has them**. An Assertion's quote stays verbatim: the stored quote is the archived text at the span, never the model's spelling. `offset_source` gains a value that says the fold was needed.

**Blocked by:** None

**Status:** superseded by `.scratch/atlas-memory-directed-reading/issues/`, ticket 02 (Claim checks); this file keeps the evidence

- [ ] At the extraction seam: a quote written with ASCII hyphens is placed on parsed text that has U+2011, the Assertion's quote is the parsed text's, and its span check passes.
- [ ] A quote that differs by a word is still `quote_mismatch`; a quote the fold makes ambiguous is `quote_ambiguous`.
- [ ] Decision entry (the fold's character table; why the stored quote is the archive's).
