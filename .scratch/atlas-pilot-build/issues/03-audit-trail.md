# 03: Audit trail and actor

**What to build:** Every mutation can record an append-only, hash-chained audit event with the configured actor, in the same transaction as the change. The database itself rejects edits to the trail. Spec Part A: Audit module, stories 43–45.

**Blocked by:** 01 (Walking skeleton)

**Status:** done

- [x] A direct UPDATE or DELETE on audit events fails at the database level (trigger and role privileges)
- [x] Chain verification detects a tampered or missing event
- [x] The actor comes from configuration and is required by every mutating service
