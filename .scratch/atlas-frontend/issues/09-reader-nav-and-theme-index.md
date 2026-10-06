# The reader's way in: nav and the theme index

Type: build
Status: resolved
Blocked by: 08

## Question

Split the nav into the reader's items (the theme index, Hypotheses, companies) and an Operations group (Memory, Relationships, Exceptions queue, Research workbench, sources); make `/` the theme index: per theme, its research questions with their latest result (an investigation's stop and headline from its research card, "draft" until a Hypothesis exists, the Hypothesis's Thesis Statement once one does), each linking to where the reader goes next; the Companies table moves to `/companies/`. Settle the layout with a one-screen sketch first, in the same visual language as ticket 08's chosen page. Workflow with Sonnet implementers; reviews; implementation log.

## Answer

Built on `frontend/memory-coverage` (`b9e1992`, review fixes `9d1f01c`; e2e `ec64673`): the nav leads with the reader's items (Research `/`, Hypotheses, Companies `/companies/`) and keeps Operations apart and quieter (Memory, Relationships, Exceptions queue, Research workbench, Themes); `/` is the research index: per theme its questions, newest first, a question asked again collapsed into one row with "n runs", a Hypothesis's Thesis Statement leading the row once one exists, else the question with a reader status ("Draft · needs review"), the date and the seed companies; the Companies table moved to `/companies/` without its CLI hint. The reader's visual language is in `globals.css` as `reader-*` classes. API gap for the lead: no card headline or finding count in the investigations list. Entry in `docs/implementation-log.md`.
