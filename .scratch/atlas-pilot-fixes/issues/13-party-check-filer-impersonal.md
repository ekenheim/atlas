# 13: The party check rejects the filer's own impersonal sentences and slide bullets

**What to build:** In investigation 1 on 0.2.5 (`ead2b86e-3556-42ba-9f3e-08660a938f98`), 9 of 15 rejections were `party_not_in_quote`, and they cost the run its most direct evidence:
- "The non-exclusive agreement includes an NVIDIA multi-billion-dollar purchase commitment and future access and capacity rights for advanced laser and optical networking products." (Coherent's 8-K filed 2026-03-02; the same sentence for Lumentum with "advanced laser components"): proposed four times as `supplies` or `buys_from`, rejected because the quote names NVIDIA but not the filer.
- "On track to double internal InP output by year-end and more than double again by 2027" and "6-inch platform producing EMLs, CW lasers, and photodiodes, with higher yields than 3-inch lines" (Coherent's EX-99.2 slides): a slide bullet names no company.
- "while also operating multiple 6-inch GaAs VCSEL manufacturing facilities." and "This includes semiconductor laser chips, laser sub-assemblies, line subsystems and wavelength management systems.": a clause or sentence whose subject is in the sentence before.

The check accepts first-person language ("we", "our") for the filer but not an impersonal sentence of the filer's own document. Extractions `be086921-ee92-41c2-a715-90840b24595e` and `40d93d72-826c-415a-8348-b7642ed301ac` hold the rejected Claims.

Decide and build: when the filer is a party and the quote is from the filer's own document, what stands in for its name. Options: (a) accept the filer as an unnamed party when the other party or the object is named in the quote and the predicate's cue is present; (b) require the model to widen the quote to the sentence that names the company or says "we"; (c) accept only for slide and press-release exhibits. The co-mention rule must hold: a sentence that names two other companies still proves nothing about the filer.

**Blocked by:** None

**Status:** needs-triage

- [ ] The decision, in `docs/decisions.md`, with the co-mention rule restated.
- [ ] At the extraction seam: the NVIDIA purchase-commitment sentence from the recorded shape of Coherent's 8-K yields an accepted `supplies` Claim (Coherent → NVIDIA); a sentence naming two other companies is still rejected.
