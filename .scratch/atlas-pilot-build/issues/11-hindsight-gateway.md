# 11: Hindsight gateway and recorded fake

**What to build:** All Hindsight access goes through one typed gateway that encodes the pinned-version rules. It's tested against a transport-level fake built from the 58 recordings. Spec Part B: Hindsight gateway module and Testing Decisions; docs/hindsight-feature-matrix.md.

**Blocked by:** 01 (Walking skeleton)

**Status:** done

- [x] Typed operations: batch retain, operation status, scoped recall, reflect with an optional schema, memory lookup, bank template apply, mental-model create/refresh/history, LLM request log
- [x] Contract tests assert that the gateway parses every recording correctly
- [x] `tags_match=any` and union-type schemas are rejected before any call; operation outcomes are decided only by `status`, with a polling timeout
- [x] The alternative listing routes are used (observations via the memory list, pages via the tree)
