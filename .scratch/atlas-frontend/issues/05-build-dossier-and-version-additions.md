# Build the dossier and version page additions

Type: build
Status: resolved
Blocked by: 04, 10

## Question

Rescoped 2026-10-06: build ticket 10's assessment-first dossier, with ticket 04's pieces placed where ticket 10 puts them (the memory strip and source-type chips under Records), and ticket 04's Memory section on the version page: the dossier's Memory block and source-type filter, the version page's memory section, client methods, pure logic in `lib/` with unit tests, e2e updated. Workflow with Sonnet implementers; `emil-design-eng` and `break-ui` reviews; implementation log.

## Answer

Built on `frontend/memory-coverage` (`563ac29`, review fixes `9d1f01c`, the lead's lazy Records): `/company/` opens findings first: kicker and key facts, In the research (the questions that seeded the company), What Atlas found (its Relationships as plain sentences by kind, with review state, the quote fetched on expand; rejected and superseded quotes never shown), and Records folded below (rendered only once opened: the existing dossier sections, Source Documents with type chips, the memory strip from the whole bank). The version page has its Memory section. API gaps for the lead: Atlas's one-line company view, open questions per company, a publication time on Evidence and Source Documents. Entry in `docs/implementation-log.md`.
