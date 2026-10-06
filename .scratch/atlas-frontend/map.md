# Map: the frontend, reader first

Label: wayfinder:map

## Destination

Redrawn 2026-10-06 (the owner): **the website is where Atlas presents its Hypotheses to a reader** who wants to understand and consume the thesis and its evidence; Atlas produces them, automated with LLMs as far as it can. This map reaches:
- **The reader's way in, merged on main** (green on lint, typecheck, test, build and the runners' e2e): the nav split into the reader's items and an Operations group; the landing page as the theme's index of research questions and their latest result; the Company dossier leading with what Atlas found about the company, its records folded below.
- **The Hypothesis reader page, prototyped with the owner** on real research-card data, handed to the next effort's spec (`.scratch/atlas-bottleneck-argument/spec.md`) as its design input. Its production build belongs to that effort, after the pilot's verdict.
- Already built on the way: the dark theme and the Memory page (an Operations tool).

## Notes

- **What the site is for (the owner, 2026-10-06):** Atlas's job is to find bottlenecks, come up with a thesis and provide evidence for it; the website presents that to an end user who wants to understand and consume the thesis. Pages for the reader lead with Atlas's conclusion and its evidence; records (spans, sources, memory, identity) are one click deeper. Operations pages (Memory, edges, exceptions, sources) serve checking and sit in their own nav group. Term: a **Hypothesis**, headed by its **Thesis Statement** (glossary; the owner kept it).
- **Boundary (from the lead's note, 2026-10-06):** build only on data that is settled (memory health, the ledger, the queue). The investigation, research card and Hypothesis pages wait for the verdict: the next effort will likely rewrite the card as a structured bottleneck argument, and the five verdict runs are reviewed on the pages as they are now. **No API shape change without a ticket in the pilot map:** a page that needs a field or endpoint ships without it ("not available yet") and the gap goes to the lead.
- **This map carries execution.** Decision tickets (`prototype`, `task`) come first, then one `build` ticket per page.
- **Branch:** `frontend/memory-coverage` (off main). Use the generated client (`frontend/lib/api/schema.ts`), never edited by hand; new calls go in `lib/api/client.ts`. Pure logic in `frontend/lib/*.ts` with unit tests in `frontend/unit/`; the page through the e2e.
- **Audience and form:** the reader first (the owner consuming theses); the Operations pages for the lead checking Memory before a verdict run. Desktop-first; the reader's pages are calmer and more spacious than the Operations pages' dense tables, readable at phone width with no horizontal scroll. The current pages' look is kept (Jakob's law within Atlas). No chart or animation library (Occam's razor): a CSS stacked bar per company carries the shape, the table the numbers.
- **The reader's visual language (ticket 08):** a calm single column (~52rem), the conclusion as a large headline, uppercase muted section labels, status pills (supported green, disputed amber, unknown grey), quotes as cards with who · source · date · Source link, records as a last line. Pages for the reader use it; Operations pages keep the dense tables.
- **Colour:** all of Atlas in one dark theme, no toggle (the owner, 2026-10-06; ticket 07), tokens on `:root`. Colour is spent only on gaps (red) and warnings (amber), so they stand out (Von Restorff); healthy is quiet grey.
- **Words and actions (the owner, 2026-10-06):** terse: labels, figures and a few words, no prose paragraphs. **Never a CLI command or runbook text on a page**: Atlas runs on k8s and the owner does not run commands from the web. A page says what is wrong and links to where to look; an action appears only where an API endpoint performs it.
- **Skills each build ticket uses:** `emil-design-eng` (end with its Before/After review table), `break-ui` (a worst-case pass: zero companies, a 40-char name, 100k facts, every listing `unavailable`), `mobile-native` basics; `animate`/`review-animations` only for expand/collapse and state changes, honouring reduced motion (the default answer for a data tool is not to animate). `tdd` for the pure modules.
- **UX checklist** (each build ticket records which law decided what):
  - **Hick / Miller:** at most 7 columns or signals in a view before a row expands; one primary action per block.
  - **Fitts / minimize target distance:** whole rows are links; filters sit beside what they filter.
  - **Proximity / similarity / uniform connectedness / Prägnanz:** a company's counts, bar and gap badge in one row; the same bar and state names everywhere (Memory page, dossier, landing); related counts in one bordered group.
  - **Serial position / peak-end:** open items first; the page ends on a one-line verdict ("9 of 12 companies complete").
  - **Zeigarnik:** an explicit count of open gaps, so the unfinished stays visible.
  - **Doherty:** first content under 400 ms; slow parts render as they arrive (ticket 01 measured: one request and a skeleton).
  - **Tesler:** the page computes shares, ages and totals; the reader never adds.
  - **Postel:** tolerate `unavailable` sub-blocks, nulls and unknown states; render what is there.
  - **Parkinson / Pareto:** each build ticket is one session; build the 20% that answers "is Memory complete and balanced?" first.
- **Agents (user, 2026-10-06):** build tickets run as a Workflow (`workflow-authoring` skill) with Sonnet implementers where the work is specified (pure modules, client methods, a page from an agreed prototype, e2e), and the orchestrator (Opus) auditing each artifact, holding the design review and merging. HITL tickets (prototypes) stay in the main session.
- **Who decides:** the lead delegated these pages; decisions here are the agent's with the user (2026-10-06 grilling: Q1–Q11 accepted as recommended; the reframe's Q1–Q4 accepted as recommended).

## Decisions so far

- Charting grilling (2026-10-06): execution in the map; order Memory → dossier/source → landing; `/` becomes status-and-links and the Companies table moves to `/companies/`; tokens, no chart library; dossier gets a Memory block from `memory/health?company_id=`, a source-type filter, per-version memory only on the version page; API gaps ship as "not available yet".
- [How fast memory/health and the dossier answer on production](issues/01-memory-health-latency-measured.md): health 0.65 s median (0.91 worst), so one request and a skeleton; the dossier's Memory block is its own parallel request (the dossier is 1 MB). Innolight's zero versions must show as a gap.
- [What the Memory & coverage page shows and in what order](issues/02-memory-page-prototype.md): variant D, dark and terse: five figures, the open items, a 7-column company table with a Facts sort, a one-line footer; no commands. Prototype on `prototype/memory-page`.
- [Atlas in one dark theme](issues/07-dark-theme-for-atlas.md): tokens on `:root` from variant D, every page dark, structure unchanged; all text passes WCAG AA.
- [Build the Memory & coverage page](issues/03-build-memory-page.md): `/memory/` built as variant D, with tested derivations in `lib/memory.ts` and a shared version bar for the dossier and landing page to reuse; the e2e passed on production data, the seeded run is the runners'.
- [What the dossier and version pages add about coverage and memory](issues/04-dossier-and-version-prototype.md): variant A (a memory strip, source-type chips, a Memory section on the version page); then the owner's verdict that the dossier is "a nightmare" for a reader, which redrew this map.
- Reframe grilling (2026-10-06): the site presents Hypotheses to a reader; "Hypothesis" stays the term; the reader page is prototyped now as the next effort's design input and built after the verdict; this map narrows to the reader's way in (nav, landing as theme index, assessment-first dossier); the status landing page is dropped; how much of the publish gate stays manual goes to the next effort's spec as an open question.
- [What a reader sees when opening a Hypothesis](issues/08-hypothesis-reader-prototype.md): variant A, the argument as rows: the Thesis Statement as headline, confidence and tally, six steps with status and for/against counts, each expanding to its quotes; open questions; records last. Linked from the bottleneck-argument spec as its design input; prototype on `prototype/thesis-reader`.

## Not yet specified

- **The probe report on a page.** `scripts/memory_probe.py` writes to `.scratch/live-runs/` and no API serves it. A page needs an endpoint: an API gap for the lead's map, not for this one.
- **The dossier's 1 MB payload.** `GET /companies/{id}/dossier` returns 963 KB of financials for Lumentum; a leaner read would be an API change, so it goes to the lead if the dossier ticket finds the page slow.
- **The theme map for a reader.** `/theme/` lists companies by layer and edges; whether the reader's theme index (ticket 09) replaces or links it waits on ticket 08's page.
- **Queue and budgets.** `GET /api/v1/queue` (pause, window, budgets, pending by kind) may deserve its own block on the Memory page or its own page once the landing page shows how often it is read.
- **Reconciliation history and triage audits.** `GET /api/v1/memory/reconciliations` and `GET /api/v1/triage/audits` are stable; ticket 02 left them off the Memory page. A page of their own if the lead reads them often.
- **Entity split as a Memory-quality signal.** No company resolves to one entity in Memory (Coherent 48). The page shows it; whether it is a defect is the lead's, raised with the hand-off.
- **The e2e seed for Memory.** The spec targets the workbench database (Coherent retained); confirmed only when the runners run it. `scripts/e2e.py` crashes on Windows before seeding (`npx` without a shell): a portability gap for the lead, not this map.

## Out of scope

- Production builds of the investigation, research card and Hypothesis pages: the next effort's, after the verdict (lead's note; the owner's reframe keeps it). Their prototype is in scope (ticket 08).
- [The status-and-links landing page](issues/06-build-landing-page.md): dropped by the reframe; its signals are on the Memory page, and `/` becomes the reader's theme index (ticket 09).
- Any API field or endpoint: goes to the pilot map as a ticket, never built here.
