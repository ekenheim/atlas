# 02: Claim checks: the filer's own sentences, typographic characters, constraint and ownership cues

**What to build:** The extraction's deterministic checks stop losing right Claims and stop accepting two kinds of wrong ones. The evidence is pilot investigation 1 on 0.2.5 (`.scratch/pilot/results.md`, "Investigation 1, third run") and pilot-fix tickets 13, 14 and 19 (`.scratch/atlas-pilot-fixes/issues/`), which this ticket supersedes.

Spec: `.scratch/atlas-memory-directed-reading/spec.md` ("Filer as the unnamed party", "Typographic fold", "Cues").

1. **The filer as the unnamed party.** A Claim whose subject or object is the company that filed the document is accepted without that company's name in the quote when: the quote is from the filer's own document; it names the other party (for a company object) or the object product; it carries the predicate's cue; and it names no other universe or counterparty company that could be the unnamed party. Recorded on the Claim as `party_basis: filer` (`named` otherwise). A sentence naming two other companies still proves nothing about the filer.
2. **Typographic fold.** A quote is located in the passage through a one-to-one character fold: hyphens U+2010 to U+2015 and U+2212 to `-`, curly quotes to straight, non-breaking and narrow spaces to a space. The Claim's and the Assertion's quote is the archived text at the span; `offset_source` is `folded` when the fold was needed. A quote the fold makes ambiguous is `quote_ambiguous`.
3. **`capacity_constrained` needs a constraint cue:** shortage, supply allocation, demand exceeding or outpacing supply, sold out, lead times, unable to meet demand. "capital allocation" and a bare "expand capacity" are not cues. Record in the ticket why fix 09's `generic_object` rule let "manufacturing capacity" through, and close the gap.
4. **`owns` runs from the holder to the issuer.** In a sentence of issuance or purchase ("issued and sold … to X", "X purchased … shares of"), the holder is the subject; the issuer as subject is rejected with a reason that names the direction.

**Blocked by:** None (can start immediately)

**Status:** done

- [x] At the extraction seam: "The non-exclusive agreement includes an NVIDIA multi-billion-dollar purchase commitment and future access and capacity rights for advanced laser and optical networking products." in the filer's document yields an accepted `supplies` Claim, filer → NVIDIA, `party_basis: filer`; the same sentence in a third party's document is rejected; a sentence naming two other companies is rejected.
- [x] A slide bullet with U+2011 ("6‑inch platform producing EMLs, CW lasers, and photodiodes") quoted with ASCII hyphens is accepted as `manufactures` with `offset_source: folded` and the archived text as its quote; its Assertion's span check passes.
- [x] Unit tests of the cues: "prioritizing investments to expand manufacturing capacity" and "capital allocation" are not `capacity_constrained`; "demand is outpacing our current supply", "industry-wide shortage" and "decisions on supply allocation" are.
- [x] "issued and sold 7,788,161 shares of Common Stock" to NVIDIA: NVIDIA `owns` the issuer is accepted, the issuer `owns` NVIDIA is rejected.
- [x] Decision entries (the filer rule with the co-mention rule restated; the fold's character table); migration for `party_basis` with the revision the lead names; prompt examples in the Investigator's next version.

## Resolution (2026-10-01)

Built as specified; the rules are in `docs/decisions.md`, "Claim checks: the filer as the unnamed party, the typographic fold, constraint and ownership cues", and the results in `docs/implementation-log.md`.

**Why fix 09's `generic_object` rule let "manufacturing capacity" through.** The rule calls an object generic when every word of it is in a fixed list (`_GENERIC_WORDS` in `backend/atlas/claims/predicates.py`), and fix 09 wrote that list from the two sentences that exposed it: the materials-and-components vocabulary ("materials", "components", "equipment", "parts", "packages", "suppliers", "raw", "key", "certain" and the like). "manufacturing" and "capacity" were not in it, so "manufacturing capacity" counted as a particular product. Fix 09's own unit test even used "manufacturing capacity" as the object of a `capacity_constrained` cue case (a Lumentum risk-factor sentence), so nothing flagged it. The Coherent Claim was then accepted because the bare cue stem "allocat…" matched "capital allocation".

**The gap, closed.** The capacity vocabulary is now generic too: capacity, capacities, manufacturing, production, output, facility, facilities. Two effects, both tested: an object made only of generic words ("manufacturing capacity", "production capacity", "our facilities") is `generic_object` for a bottleneck predicate; and, because the same list decides which words of an object must occur in the quote, a quote that says only "manufacturing capacity" no longer names "EML manufacturing capacity" (`object_not_in_quote`). "6-inch InP manufacturing capacity" and "indium phosphide capacity" stay particular. The rule still applies to the four bottleneck predicates only; `expands_capacity_for` keeps its behaviour (the prompt tells the model to name the product).

**Beyond the ticket's four items** (each recorded as a deviation in the log): a second reading of direction from the wording, "the company whose purchase commitment it is, is the buyer", because the filer rule would otherwise accept the pilot's `buys_from` proposals for the NVIDIA sentence; and the stray-company test also counts a name written with a legal form, so an unknown company is not invisible to the co-mention rule.

**Not covered:** the Skeptic's own quote placement (`backend/atlas/investigations/skeptic.py`) is not folded; "X made an investment in Y" is not read for direction; an unknown company written without a legal form is not seen as a stray.
