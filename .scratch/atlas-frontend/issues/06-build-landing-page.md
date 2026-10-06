# Build the status-and-links landing page

Type: build
Status: resolved (out of scope)
Blocked by: 03

## Question

`/` becomes status and links; the Companies table moves to `/companies/` (the nav's Companies link with it; e2e that start at `/` updated). Four signals, each a link to where it is acted on: open memory gaps (versions `not_submitted` + `triage_failed`, from `memory/health`), the queue's pause (`GET /api/v1/queue`), the last reconciliation's status, open exceptions (`GET /api/v1/relationships/exceptions`'s total). Quiet when healthy, coloured when not (Von Restorff); then the links to every page, grouped (Memory and sources; research). A layout question small enough to settle in the ticket with a one-screen sketch; if not, it splits into a prototype first. Workflow with Sonnet implementers; reviews; implementation log.

## Answer

Out of scope (2026-10-06): the owner's reframe makes `/` the reader's way in, not an operator's status board. Its four signals are on the Memory page already. Replaced by ticket 09.
