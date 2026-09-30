# 22: First cluster deploy and smoke test

**What to build:** Atlas runs in the home cluster and the Phase 2 'same flow works in the cluster' gate is verified. The owner opens and merges the home-ops PRs in order and runs the provisioning steps; the agent supports each step and provides a smoke script. Spec Part B: Deployment rollout order; stories 36–44.

**Blocked by:** 17 (Live test suite), 21 (Home-ops Atlas releases (PRs 4 and 6))

**Status:** done

- [ ] The smoke script checks readiness, one small ingest and one resolved recall against the deployed instance
- [ ] Each rollout step is confirmed healthy before the next PR is opened
- [ ] The implementation log records the deployed versions, routed models and smoke results
