# 24: An Investigator reads its company's latest periodic report, whatever the pointers name

**What to build:** An Investigator's documents always include its company's latest annual or quarterly report and its latest results release when it has them, beside the documents the pointers name. Today every document can be a transcript, and what the filings say goes unread.

Evidence: production 0.3.1, investigation `452c3b9d-2e2f-4cc6-bc54-5130155b9aac` (pilot investigation 1, fifth run; reviewed in `.scratch/pilot/results.md`, "Investigation 1, fourth and fifth runs"). Lumentum's Investigator took 4 documents (two conference appearances, the Q2 2026 and Q4 2026 calls) and dropped 221; Coherent's took 5 transcripts and dropped 349; `documents_pointed` equals `documents` for both. Neither read a 10-K, 10-Q or 8-K. Lost with them: Lumentum's allocation statement in its 10-K, NVIDIA's purchase commitments, the slides' capacity figures, and the five baseline hits the card covers only in substance (Coherent's "3X InP capacity increase" and Sherman figures, 250 million InP lasers shipped, the 200G-VCSEL 1.6T ramp, Lumentum's 200G EML shipments). The document budget is 25 for six Investigators, so each takes about four, and the pointers name transcripts first because that is what Memory holds most of.

- An Investigator's document list has a floor: its company's latest periodic report (10-K, 10-Q, 20-F, 6-K results, or the exchange's annual or interim report) and its latest results release (an 8-K exhibit 99.1 or the exchange's equivalent) available by the as-of time, when the company has them; then the pointed documents, best pointer first; then its latest ones, as today. The floor is inside the Investigator's share of the document budget; when the share is smaller than the floor plus one pointed document, the periodic report and the best-pointed document are taken.
- Passage selection already keeps a floor of one passage for each periodic report and results release; nothing changes there.
- The Investigator task's artifacts say which documents came from the floor (`documents_floor`); the card's `read` shows it.
- `docs/decisions.md`, "Multi-hop Investigators": the floor and why (Memory points at what it holds most of).

**Blocked by:** None

**Status:** done

- [x] Integration test at the investigation seam: a company whose pointers all name transcripts, with a 10-K and an 8-K exhibit in the archive: the Investigator's documents include the 10-K and the exhibit and the best-pointed transcript, within its share; the artifacts name the floor.
- [x] A company with no periodic report (transcripts only) takes its pointed documents as today.
- [x] A share of 2 takes the periodic report and the best-pointed document.
- [x] Decision entry; `AGENTS.md` line.

Notes (implementer): exchange annual/interim reports are not in the floor (no form type in the ledger; selection's notion, reused as asked, does not cover them); a share of 1 takes the periodic report. See `docs/decisions.md`, "Multi-hop Investigators", "The document floor".
