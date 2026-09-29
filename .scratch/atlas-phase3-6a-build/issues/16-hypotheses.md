# 16: Hypotheses

**What to build:** An investigation's result is saved as a Hypothesis (statement, mechanism, predictions, catalysts, falsifiers, required Evidence, alternatives; §5.6, §8.1), drafted by the Editor. It follows the §5.6 lifecycle; published versions are immutable and corrections are new versions. Two versions can be diffed (new, contradicted, unchanged claims) and exported as JSON/Markdown with citations and run metadata.

Spec: `.scratch/atlas-phase3-6a/spec.md`.

**Blocked by:** 14 (Investigation orchestration)

**Status:** done

- [x] Hypothesis and version schema with the lifecycle enforced
- [x] Editor role produces a draft from an investigation
- [x] `hypotheses` create/get/diff/export API
- [x] Gate test: an end-to-end fixture investigation reaches a reviewable Hypothesis with a source trail, ≥1 falsifier and ≥1 unresolved question; no unsupported claim is promoted
