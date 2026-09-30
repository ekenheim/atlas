# 26: §15 photonics demo gate, release and deploy

**What to build:** The Phases 3–6a gate runs end to end on the photonics theme, then Atlas is released and deployed to the `development` namespace.

Spec: `.scratch/atlas-phase3-6a/spec.md`.

**Blocked by:** 05 (LSE RNS adapter (IQE)); 06 (Euronext / issuer regulated-information adapter (Soitec)); 09 (Candidates); 13 (Edge table page (C)); 17 (Research workbench page (D) and follow-up round); 21 (Contradiction proposes an update); 22 (Replay banks); 23 (Theme explorer (A) and Company dossier (B)); 24 (Hypothesis dossier page (E)); 25 (Evaluation set)

**Status:** in-progress (0.2.0 released; home-ops PR #7119 awaits the owner's merge)

- [ ] All §14 Phases 3–6a gate tests pass in `scripts/ci.sh`
- [ ] Opt-in live scenarios for discovery and one investigation run with the owner's go-ahead; results logged
- [ ] Version tag released; home-ops PR with any new settings/secrets
- [ ] Implementation log updated; nothing claimed live that ran only on fixtures
