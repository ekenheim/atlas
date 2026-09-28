# 21: Home-ops Atlas releases (PRs 4 and 6)

**What to build:** Prepared and validated local branches for the dedicated Hindsight release and the Atlas app release in `datasci/atlas/`, ready for the owner to open once prerequisites are live. Spec Part B: Deployment; map ticket 09.

**Blocked by:** 12 (Hindsight in Compose and bank template), 16 (Mental models), 18 (Release pipeline), 19 (Archive provisioning script), 20 (Home-ops prerequisites (PRs 1–3))

**Status:** parked (owner: repo-only focus for now; resume when asked)

- [ ] The Hindsight release matches the spec (same digest, Recreate, stable worker ID, tenant key, no TEI, no API route, internal control-plane route)
- [ ] The app release: api and worker controllers with resources, ExternalSecrets (one per Secret), the internal route with a private-CIDR policy, the nightly R2 copy CronJob, ServiceMonitor, PrometheusRule and a Gatus in-cluster check
- [ ] flux-local, kubeconform and yamllint pass; the R2 runbook is written; the branches are not pushed
