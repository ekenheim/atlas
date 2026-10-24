# The pages

Type: task
Status: wontfix
Blocked by: 01, 02, 04, 05

## What to build

The pages are dark and terse. Each leads with the assessment, and the records sit one click deeper (memories `owner-ui-dark-terse-no-commands` and `owner-wants-assessment-not-records`). Start from the Chokepoint Watch pages and the shell in `.scratch/atlas-ui/spec.md`.

- **Today** (`/`), in this order:
  1. The council's board as of its latest edition: rank, chokepoint, whether it is consensus or early, and a one-line reason.
  2. What changed since last week: new, killed and moved.
  3. Rewrites found.
  4. Quotes not verified, grouped by reason.
  5. Predictions due in the next 30 days, and those settled since the last edition.
- **A theme** (`/theme?slug=`):
  - its chokepoints in the latest edition, with their verdicts;
  - each quote, with its check and tier;
  - the rejected candidates;
  - its predictions;
  - its editions, listed under Records.
- **A chokepoint** (`/chokepoint?id=`):
  - its history across editions: status, verdicts, holders and kill criteria;
  - every quote that has ever supported it.
- **The record** (`/record`):
  - every prediction, with its state;
  - the calls' checkpoints, where a call is priced.

No page shows a CLI command.

## Done when

- [ ] On production, the pages render the 2026-10-19 and 2026-10-26 editions, checked in a browser at phone width.

## Comments

- 2026-10-24, lead: closed, because the owner archived Atlas (ADR 0005).
