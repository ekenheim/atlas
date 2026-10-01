# 07: The Skeptic asks Memory about each bear-checklist item and reads what it points to

**What to build:** The Skeptic reads documents on every run, chosen by what Memory holds on the bear checklist for the companies the Claims name, not by a model's plan or a fixed fallback. Evidence: `skeptic-plan.v2` chose no documents on 0.2.3 and `skeptic-plan.v3` returned an empty plan on 0.2.5 (pilot-fix ticket 17, which this supersedes); the fallback's passages were the first windows of four filings.

Spec: `.scratch/atlas-memory-directed-reading/spec.md` ("The Skeptic").

- For each company the accepted Claims name (subjects, and universe-company objects), one recall per bear-checklist item with theme scope, phrased from the item and the Claims' objects. The results are reading pointers of the Skeptic's task, stored like the Scout's.
- The Skeptic's documents and passages come from its pointers through ticket 05's selection. A company with no pointer falls back to its latest 10-K and 10-Q, as fix 06 does today.
- The plan role call keeps only the web and EDGAR queries; an empty answer there no longer leaves the Skeptic without reading.
- The rule "No Memory is sent or read" becomes "no Memory is sent to the Skeptic; Memory chooses what it reads". The independence rule is unchanged: a contradiction is independent only in an Evidence Family none of the supporting Claims use.

**Blocked by:** 01 (Reading pointers), 03 (Contradiction or bear context), 05 (Passage selection)

**Status:** done

- [x] Integration test at the investigation seam: with a memory about a seed company's customer concentration derived from its recorded 10-Q, the Skeptic reads the window holding that statement and the card shows it as bear context; a plan that answers no queries still leaves the Skeptic with documents and passages.
- [x] A company with no pointer is read through the fallback, recorded as such.
- [x] Decision entry (amends "The Skeptic reads the archive: a deterministic fallback"); the plan prompt's next version; `AGENTS.md`.

## Resolution

Built in `atlas.investigations.skeptic` over `atlas.investigations.pointers` (`record_pointers`, `skeptic_pointers`) and `atlas.claims.selection.select`. Decision: `docs/decisions.md`, "The Skeptic reads where Memory points"; log: `docs/implementation-log.md`, "memory-directed reading ticket 07".

One reading of the first box: the recorded Coherent and Lumentum 10-Qs hold a cover and financial statements only (6,738 and 11,087 characters), with no customer-concentration statement, so the acceptance test derives the memory from the recorded Coherent **10-K**'s risk factors (Item 1A, its fifth window: "A small number of customers have consistently accounted for a significant portion of our revenues, with two customers each contributing more than 10% of total revenues in fiscal 2026."). The rest of the box is as written: the Skeptic reads the window holding that statement first, the card shows it as bear context, and a plan answering no query (or quarantined) still leaves it with documents and passages.
