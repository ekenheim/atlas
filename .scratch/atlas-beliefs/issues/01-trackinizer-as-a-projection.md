# Trackinizer as a projection of one investigation, for the owner to judge

Type: prototype
Status: parked (owner)
Blocked by: none

## Why

The owner likes trackinizer's UI and graphs (2026-10-12). Before a fork or any Atlas schema work, see one real investigation's data in it. Spec §4.

## What to do

1. Run upstream trackinizer unmodified, locally, on Postgres (`uv tool install trackinizer`; its README's quick start). Record the version.
2. A one-off script (`.scratch/tools/trackinizer_project.py`, no production change) that reads one argument investigation from production's API (pilot 0.5.6 question 2 or 5) and writes, through `POST /api/inquiries/batch` and `POST /api/edges/batch` with Atlas IDs as idempotency keys: the question as a root Issue narrowed into six step Issues; each Fact as an Artifact (title: the Fact's statement; description: the quote; a URL to the production source viewer at the span; labels: company, step, status); each step statement as a Belief (`unproven`) with `proves` edges from its cited Facts (valence +0.5) and from Skeptic Facts by the counter-judge's relation (`contradicts` −1, `limits` / `dates` −0.5, `qualifies` −0.25); the open questions as Issues.
3. Screenshots of the graph, one Belief page and the Issue tree go to `.scratch/atlas-beliefs/trackinizer-review/`; the owner looks and says whether it earns a place (stakeholder view, agent workspace, neither).

## Done when

- [ ] The projection runs end to end on one investigation; counts recorded.
- [ ] The owner's verdict and the lead's notes (what the model could not hold, e.g. a span) in `## Comments`, and a line in the pilot map's Decisions.

## Comments

**2026-10-12:** the owner will pick this up personally; trackinizer is already deployed in the cluster (home-ops-upgrade PRs #7446 and #7466, `kubernetes/apps/agent-lab/trackinizer`, internal `http://trackinizer.trackinizer.svc:8765`, tokens per client from a Secret), so a projection would target that instance, not a local one. Nothing in Atlas depends on it.
