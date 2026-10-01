# The §15 demo on production

Type: task
Status: open
Blocked by: 01

## Question

START_HERE's required demonstration lists what the pilot must show running in the cluster. For each, find it on production (0.2.5) or produce it there, and record the IDs; say plainly which ones exist only in fixture tests:
- provenance-resolved Hindsight recall;
- a discovered company that wasn't seeded at startup (a Candidate, e.g. from an `edgar_fts` lead);
- a directed, reviewed, source-clickable company or product edge;
- a Hypothesis with both support and falsifiers;
- a recomputing scenario;
- a frozen Research Snapshot;
- a later contradictory source that doesn't rewrite the snapshot (a proposed update);
- an as-of replay that excludes future sources (production has no local replay Hindsight; decide whether the Compose run stands in).

Publishing a Hypothesis needs the owner's approval of its edges (ticket 09), and a replay spends Codex operations, so the answer may leave an item "shown on fixtures only" with the reason. This closes build ticket 26's remaining boxes, except the TradingView check the owner paused.
