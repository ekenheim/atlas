# 05: Archive (filesystem + S3)

**What to build:** Immutable, content-addressed objects can be stored and retrieved through one interface with a filesystem backend and an S3 backend. Both pass the same contract suite, including object-lock semantics on Silo. Spec Part A: Archive module, archive contract suite; ticket 13 of the map.

**Blocked by:** 01 (Walking skeleton)

**Status:** ready-for-agent

- [ ] Put is idempotent by hash, round-trips exactly, and never overwrites
- [ ] Against Silo with an object-locked bucket: an overwrite creates a new version, a plain delete adds a delete marker, and a permanent version delete is refused without bypass. Tests assert behavior, not exact error codes
- [ ] Archive locations are internal application URIs; no object-store credentials are exposed
