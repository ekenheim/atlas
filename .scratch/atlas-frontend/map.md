# Map: the frontend on settled data

Label: wayfinder:map

## Destination

Three pages merged on main, green on `npm --prefix frontend run lint | typecheck | test | build` and the runners' Playwright e2e:
- **Memory & coverage** (`/memory/`): what the research bank holds and lacks, per company, at a glance (from `GET /api/v1/memory/health`).
- **Dossier and source additions**: a company's memory coverage, its transcripts and other source types, and on a version what Memory holds of it.
- **A status-and-links landing page** (`/`): the few signals that need attention, and the way to each page.

## Notes

- **Boundary (from the lead's note, 2026-10-06):** build only on data that is settled (memory health, the ledger, the queue). The investigation, research card and Hypothesis pages wait for the verdict: the next effort will likely rewrite the card as a structured bottleneck argument, and the five verdict runs are reviewed on the pages as they are now. **No API shape change without a ticket in the pilot map:** a page that needs a field or endpoint ships without it ("not available yet") and the gap goes to the lead.
- **This map carries execution.** Decision tickets (`prototype`, `task`) come first, then one `build` ticket per page.
- **Branch:** `frontend/memory-coverage` (off main). Use the generated client (`frontend/lib/api/schema.ts`), never edited by hand; new calls go in `lib/api/client.ts`. Pure logic in `frontend/lib/*.ts` with unit tests in `frontend/unit/`; the page through the e2e.
- **Audience and form:** the lead and the owner, checking Memory before a verdict run, at a desk. Desktop-first and dense (an ops console, not a landing page for strangers), readable at phone width with no horizontal scroll. The current pages' look is kept (Jakob's law within Atlas). No chart or animation library (Occam's razor): a CSS stacked bar per company carries the shape, the table the numbers.
- **Colour:** a minimal token set in `globals.css` (`--ok`, `--warn`, `--gap`, `--muted`, light and dark). Colour is spent only on gaps and drift, so they stand out (Von Restorff); healthy is quiet.
- **Skills each build ticket uses:** `emil-design-eng` (end with its Before/After review table), `break-ui` (a worst-case pass: zero companies, a 40-char name, 100k facts, every listing `unavailable`), `mobile-native` basics; `animate`/`review-animations` only for expand/collapse and state changes, honouring reduced motion (the default answer for a data tool is not to animate). `tdd` for the pure modules.
- **UX checklist** (each build ticket records which law decided what):
  - **Hick / Miller:** at most 7 columns or signals in a view before a row expands; one primary action per block.
  - **Fitts / minimize target distance:** whole rows are links; filters sit beside what they filter.
  - **Proximity / similarity / uniform connectedness / Prägnanz:** a company's counts, bar and gap badge in one row; the same bar and state names everywhere (Memory page, dossier, landing); related counts in one bordered group.
  - **Serial position / peak-end:** gaps first, the next step (the runbook command) last; the page ends on what to do.
  - **Zeigarnik:** an explicit count of open gaps, so the unfinished stays visible.
  - **Doherty:** first content under 400 ms; slow parts render as they arrive (ticket 01 measures).
  - **Tesler:** the page computes shares, ages and totals; the reader never adds.
  - **Postel:** tolerate `unavailable` sub-blocks, nulls and unknown states; render what is there.
  - **Parkinson / Pareto:** each build ticket is one session; build the 20% that answers "is Memory complete and balanced?" first.
- **Agents (user, 2026-10-06):** build tickets run as a Workflow (`workflow-authoring` skill) with Sonnet implementers where the work is specified (pure modules, client methods, a page from an agreed prototype, e2e), and the orchestrator (Opus) auditing each artifact, holding the design review and merging. HITL tickets (prototypes) stay in the main session.
- **Who decides:** the lead delegated these pages; decisions here are the agent's with the user (2026-10-06 grilling: Q1–Q11 accepted as recommended).

## Decisions so far

- Charting grilling (2026-10-06): execution in the map; order Memory → dossier/source → landing; `/` becomes status-and-links and the Companies table moves to `/companies/`; tokens, no chart library; dossier gets a Memory block from `memory/health?company_id=`, a source-type filter, per-version memory only on the version page; API gaps ship as "not available yet".
- [How fast memory/health and the dossier answer on production](issues/01-memory-health-latency-measured.md): health 0.65 s median (0.91 worst), so one request and a skeleton; the dossier's Memory block is its own parallel request (the dossier is 1 MB). Innolight's zero versions must show as a gap.

## Not yet specified

- **The probe report on a page.** `scripts/memory_probe.py` writes to `.scratch/live-runs/` and no API serves it. A page needs an endpoint: an API gap for the lead's map, not for this one.
- **The dossier's 1 MB payload.** `GET /companies/{id}/dossier` returns 963 KB of financials for Lumentum; a leaner read would be an API change, so it goes to the lead if the dossier ticket finds the page slow.
- **Queue and budgets beyond the landing signal.** `GET /api/v1/queue` (pause, window, budgets, pending by kind) may deserve its own block on the Memory page or its own page once the landing page shows how often it is read.
- **Reconciliation history and triage audits.** `GET /api/v1/memory/reconciliations` and `GET /api/v1/triage/audits` are stable; whether they belong on the Memory page or under it waits on ticket 02's layout.
- **The e2e seed for Memory.** `scripts/e2e.py` seeds from the Lumentum fixtures with the Hindsight fake; whether it yields a meaningful `memory/health` (several companies, a gap, a retired section) or needs more seeding is found in ticket 03.

## Out of scope

- The investigation, research card and Hypothesis pages: wait for the verdict (lead's note, 2026-10-06).
- Any API field or endpoint: goes to the pilot map as a ticket, never built here.
