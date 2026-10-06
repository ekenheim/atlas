# What the Memory & coverage page shows and in what order

Type: prototype (HITL)
Status: resolved
Blocked by: none

## Question

The layout of `/memory/`, settled on a throwaway prototype fed with a real `memory/health` response (ticket 01's sample, else the schema with plausible numbers): which blocks, in what order, which columns of the per-company table (≤ 7; the rest in an expanded row), the stacked version-state bar and its legend, what carries colour (gaps and drift only), how `unavailable` listings, failed groups, pending-by-age, consolidation and the last reconciliation appear, and what the page ends on (the next step: the runbook command for the biggest gap). Whether reconciliation history and triage audits belong here (map: Not yet specified).

Use `prototype` (Matt's) and, for comparing genuinely different layouts, the picker approach; review with `emil-design-eng`. The UX checklist in the map's Notes is the yardstick. The answer is the agreed layout, linked as an asset, that ticket 03 builds.

## Answer

**Variant D** (the owner, 2026-10-06), a mix of the three first drafts, captured with them on the throwaway branch `prototype/memory-page` (commit `1aef8c6`; `npm --prefix frontend run dev`, then `/prototype-memory/?variant=A|B|C|D`). The owner rejected the light theme, the prose and every CLI command: Atlas runs on k8s and the owner never runs commands from a page.

The layout ticket 03 builds:
1. **Title** "Memory".
2. **Five figures** in one bordered strip: Open (count, coloured if any; "n gaps" below), Versions in memory (% of the versions inside the intake window; "x of y in window"), Facts (with observations below), Consolidation (age of a running run in amber when over 24 h, else "idle"; rounds below), Reconciliation (status; age below; red unless clean).
3. **Open** (only when anything is): one line per item, gaps before warnings: a dot (red gap, amber warning), the name (a company links to its dossier), a status tag, a few words of detail. Items: a company with no version ("Nothing ingested"), versions not in memory (`not_submitted` + `triage_failed`), failing sections (failed + stuck + cancelled), a thin company (facts under 40% of the median researched company's: the lead's rule to tune), consolidation running over 24 h, reconciliation not clean, companies split across several entities (count, the worst named).
4. **Companies**: a 7-column table (Company, Versions bar, In memory "n / total", Facts with a depth bar to scale, Retired, Skipped, Status), a Status/Facts sort toggle; a row expands to one detail line (sections, zero-fact, below profile, stuck, facts per version, entities, Dossier link). The versions bar: in memory, in flight, retired (hatched), all skipped, gap (red); its legend under the table.
5. **Footer**: "n of m companies complete · checked … ago".

No commands, no runbook text, no prose paragraphs. Colour only on gaps (red) and warnings (amber). Counterparties are not listed. Not on the page: reconciliation history, triage audits, failed groups beyond the count (they fold into "failing sections"); they stay in the map's fog.
