# Build the Memory & coverage page

Type: build
Status: resolved
Blocked by: 01, 02, 07

## Question

Build `/memory/` to ticket 02's layout and ticket 01's loading design: client methods for `memory/health` (and any other read 02 placed on it), the tokens from ticket 07, a pure `lib/memory.ts` (shares, open items and their order, the thin rule, the figures) with unit tests, the shared version-state bar component (reused by tickets 05 and 06), a nav link, and an e2e spec (find out whether `scripts/e2e.py`'s seed gives a meaningful page; seed more through the real services if not). Workflow with Sonnet implementers; end with `emil-design-eng` and `break-ui` reviews and a line in `docs/implementation-log.md`.

## Answer

Built on `frontend/memory-coverage` (commits `fae8956` derivations, `cc0c2eb` page, `78f87e6` e2e, `13befd7` review fixes, then the lead's layout fix): `/memory/` as ticket 02's variant D, with derivations in `frontend/lib/memory.ts` (76 unit tests with `memory.test.ts`, on a trimmed copy of production's response and worst cases), the shared `frontend/components/version-bar.tsx`, `api.memoryHealth()` in `client.ts`, and "Memory" in the nav. Reviewed with `emil-design-eng` and `break-ui` (20 findings, all musts and shoulds applied). Recorded choices: a reconciliation never run is amber; the in-memory segment takes the accent colour; a company with facts but no version in the window is a warning, not "Nothing ingested".

Verified: lint, typecheck, test and build pass; the e2e spec passed (2 of 2) against production data through a local read-only preview; not yet against the seeded databases (`scripts/e2e.py` crashes on Windows: `npx` without a shell). Entry in `docs/implementation-log.md`.
