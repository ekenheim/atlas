# 01: Split the investigation document budget across seed companies; always write a card

**What to build:** In pilot investigation 1, the first Investigator task (Coherent) took all 25 documents and the second (Lumentum) read none. And because no Claim was accepted, the Skeptic, Analyst and Editor were skipped, so the researcher saw nothing. Two changes:
1. Split `max_documents` fairly across the seed companies' Investigator tasks: an equal share each, with unused share passed on in plan order.
2. The Editor always writes a research card, even with zero accepted Claims. It then lists what was searched (the Scout's queries and leads taken), which documents and sections were read per company, why nothing was accepted (the extraction outcomes), and the open questions for the next round. The stop reason is unchanged.

**Blocked by:** None

**Status:** done

- [x] With 2 seeds and a budget of 25, each Investigator task gets at least 12 documents. There is an integration test at the investigation seam.
- [x] An investigation with 0 accepted Claims ends with a card: `findings` empty, and the `searched`, `read` and `open_questions` sections filled. It's visible in the API and the workbench.
- [x] The Editor prompt version is bumped, with scripted-fake tests.
