# 10: Investigator Claims → Assertions

**What to build:** The Investigator reads archived parsed text (sections chosen via recall hits and entity tags) and proposes Claims naming a Source Version and an exact quote span. Only whitelisted predicates with explicit direction and a layer are allowed; there is no mapping from 'partners/works with'. Claims whose span validates become Assertions; the rest are recorded as `claim_rejected` with the reason.

Spec: `.scratch/atlas-phase3-6a/spec.md`.

**Blocked by:** 07 (Role-call foundation)

**Status:** done

- [x] The §5.5 predicate whitelist and the layer taxonomy in code, with direction
- [x] Accepted Claims become Assertions through the existing span check
- [x] Rejected Claims are stored with the reason and visible via the API
- [x] Gate test: a co-mention-only fixture never produces a Relationship-eligible Assertion
- [x] Metrics: Claims accepted and rejected
