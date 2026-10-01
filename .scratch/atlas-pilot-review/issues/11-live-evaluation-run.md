# The first live evaluation run

Type: task
Status: open
Blocked by: 10

## Question

Run `ATLAS_LIVE_TESTS=1 uv run atlas evaluate --live` on the adjudicated gold cases: MiniMax answers, and each case's sources are retained into a throwaway bank on the configured Hindsight. It has never been run live. It spends MiniMax tokens and Codex retains, so it needs the owner's go-ahead and room in both budgets (`/queue`).

What are the per-case checks and per-metric scores (`GET /api/v1/evaluations/{id}`), including `relationships.unexpected`, and which cases fail on the real model that pass on the scripted one?

The answer records the run ID, the scores and the cost; failures become defect tickets.
