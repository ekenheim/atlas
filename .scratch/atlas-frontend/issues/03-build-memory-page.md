# Build the Memory & coverage page

Type: build
Status: open
Blocked by: 01, 02, 07

## Question

Build `/memory/` to ticket 02's layout and ticket 01's loading design: client methods for `memory/health` (and any other read 02 placed on it), the tokens from ticket 07, a pure `lib/memory.ts` (shares, open items and their order, the thin rule, the figures) with unit tests, the shared version-state bar component (reused by tickets 05 and 06), a nav link, and an e2e spec (find out whether `scripts/e2e.py`'s seed gives a meaningful page; seed more through the real services if not). Workflow with Sonnet implementers; end with `emil-design-eng` and `break-ui` reviews and a line in `docs/implementation-log.md`.
