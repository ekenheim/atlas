# 08: Assertions and review

**What to build:** The researcher can record an Assertion bound to an exact quote span in a parsed Source Version, then review and supersede it without edits. Spec Part A: Assertions module, stories 37–42.

**Blocked by:** 07 (Ingest a Lumentum filing end to end)

**Status:** done

- [x] An Assertion whose quote doesn't occur at the given anchor in the archived parse is rejected
- [x] New Assertions are `unreviewed`; review transitions follow spec §5.4; supersession links to a successor and never edits
- [x] Listing by company and review state works; every create/review writes an audit event
