# 19: Archive provisioning script

**What to build:** The owner can create the cluster archive bucket and its scoped user by running one re-runnable script. Spec Part B: Deployment (archive); map ticket 10.

**Blocked by:** 05 (Archive (filesystem + S3))

**Status:** done

- [x] The script creates `atlas-archive` with object lock, Governance mode and 10-year default retention, plus an `atlas` user and policy without bypass rights, and prints credentials for Bitwarden
- [x] Running it twice changes nothing
- [x] It's verified against Silo; the runbook documents running it with root credentials
