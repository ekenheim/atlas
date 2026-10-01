# 19: `capacity_constrained` from an expansion statement; `owns` reversed for a share issuance

**What to build:** Two wrong Claims were accepted in investigation 1 on 0.2.5 (`ead2b86e-3556-42ba-9f3e-08660a938f98`). The Reviewer sent both to the exceptions queue, so neither became a verified edge, but both count against Claim precision and one reached the card's Claims.
- **Coherent `capacity_constrained` "manufacturing capacity"** (Claim `f34f343c-da43-46f6-8969-ef6e19cbe200`): "we remain disciplined in our capital allocation, prioritizing investments to expand manufacturing capacity so we can efficiently fulfill the ongoing acceleration in customer demand." The sentence states an expansion. `capacity_constrained` needs language of constraint in the quote: a shortage, an allocation, demand exceeding or outpacing supply, sold out, a lead time. "capital allocation" must not count as an allocation cue. The object is also generic, which fix 09's `generic_object` rule should have refused: check why "manufacturing capacity" passed it.
- **Lumentum `owns` NVIDIA** (Claim `f56eff50-f67a-40b9-aab5-f8380d46a81b`): "Lumentum Holdings Inc. … completed the issuance and sale of 2,876,415 shares of the Company's Series A Convertible Preferred Stock … to NVIDIA Corporation". The issuer is not the owner. For `owns`, the buyer or holder of the shares is the subject: "issued and sold … to X" and "X purchased" both mean X owns part of the issuer. The Coherent Claim from the parallel sentence got the direction right (NVIDIA `owns` Coherent).

Add both as deterministic cue checks where the directional-language checks live, and as examples in the Investigator's prompt.

**Blocked by:** None

**Status:** superseded by `.scratch/atlas-memory-directed-reading/issues/`, ticket 02 (Claim checks); this file keeps the evidence

- [ ] Unit tests of the cues: the Coherent sentence is not `capacity_constrained`; "demand is outpacing our current supply", "industry-wide shortage" and "supply allocation" are; "capital allocation" is not.
- [ ] At the extraction seam: an `owns` Claim whose subject is the issuer in an "issued and sold … to" sentence is rejected with a reason that names the direction; the buyer as subject is accepted.
- [ ] Why `generic_object` let "manufacturing capacity" through, recorded in the ticket, and fixed if it is a gap.
