# 06: Multi-hop Investigators: the companies the pointers name are read, not only the seeds

**What to build:** An investigation seeded with Coherent and Lumentum reads AXT's filings when Memory points there. Evidence: the recall probe in the spec (AXT's 6-inch InP supply agreement with Coherent and its export-permit backlog, found by the Scout's kind of query with theme scope, in documents the investigation never opened).

Spec: `.scratch/atlas-memory-directed-reading/spec.md` ("The plan grows after the Scout", "Document choice").

- After the Scout, companies are ranked by their reading pointers (count weighted by rank). Every seed gets an Investigator, as today. Other universe companies (role `researched`; never a counterparty, which has no archive) get one in rank order while the company budget has room: a new setting, default 6 Investigators per round; a request may lower it.
- An Investigator takes the Source Versions its company's pointers name, best pointer first, then its latest documents as today, up to its share of the document budget (shared across all Investigators of the round).
- The investigation's plan, events and read show which Investigators were added and why (the pointers). The research card's `read` has a row per Investigator; the Financial Analyst still proposes scenario inputs for the seed companies only.
- A follow-up round does the same with its question's pointers.
- A company with pointers and no room is listed on the card as not read, so the next round can seed it.

**Blocked by:** 01 (Reading pointers), 05 (Passage selection)

**Status:** done

- [x] Integration test at the investigation seam: seeds Coherent and Lumentum, memories derived from a third universe company's recorded filing answering the Scout's query; the plan gains that company's Investigator, it reads the pointed document's pointed window, its accepted Claim is on the card, and the edge between the third company and a seed is formed. *(Met with one deviation: the third company's document is a hand-shaped AXT note, labelled so, not a recorded filing. The recorded fixtures hold filings of Coherent and Lumentum only, and neither states a relation to the other. A second test, on the recorded filings, shows Lumentum gaining an Investigator that reads its recorded filings when Coherent alone is the seed.)*
- [x] With a company budget of 2 and three pointed companies, the two seeds are read and the third is listed as not read.
- [x] A counterparty company with a name match in Memory gets no Investigator. *(The test shows the name match giving nothing. A pointer can't carry a counterparty's company: it has no archive. The ranking filters on the role besides; no test can make that filter fail through a public interface.)*
- [x] The workbench page shows the added Investigators (API client regenerated); decision entry; settings; `AGENTS.md`.

**Built** (`docs/decisions.md`, "Multi-hop Investigators: the plan grows after the Scout"; `docs/implementation-log.md`): the ranking weight is the sum of 1 / rank over a company's Scout pointers; the budget is `ATLAS_INVESTIGATION_MAX_COMPANIES` (6) and `budgets.max_companies` (migration `0058`, `investigation.max_companies`); the plan grows in `advance`, once per round, when the Scout has succeeded.
