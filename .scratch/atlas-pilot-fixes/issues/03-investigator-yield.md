# 03: Investigator yield on bottleneck evidence (diagnose, then decide)

**What to build:** In pilot investigation 1, the Investigator read 24 passages from Coherent's FY2026 10-K Items 1 and 1A and proposed no Claims in any of its 4 calls. Diagnose why, from the archived passages (reproducible offline against the recorded passages, then live on MiniMax with the owner's standing go-ahead):
- Does the prompt's strictness suppress self-statements, such as "we manufacture InP lasers" (`manufactures`, a product object) or "we are expanding capacity for …" (`expands_capacity_for`)?
- Or does the Claim model lack a way to state company-level bottleneck facts: sole or single sourcing without a named counterparty, demand exceeding supply, allocation, in-house feedstock?

Deliver a short report with numbers from prompt variants on the same passages, and a recommendation. That's either a prompt fix, or a design proposal for company-level bottleneck Assertions (for example `constrained_in`, `sole_sources`, `vertically_integrates`) with direction, layer and exact quotes. A new predicate is a domain-model change: it goes into `CONTEXT.md` and `docs/decisions.md`, and the owner decides.

**Blocked by:** None

**Status:** ready-for-agent

- [ ] An offline replay harness reproduces the pilot's extraction: the same passages and prompt, with the scripted and the live model.
- [ ] Live comparison of the current prompt against at least two variants: Claims proposed, accepted, rejection reasons and tokens.
- [ ] A recommendation, written up in the report.
