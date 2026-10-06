# What the dossier says first: what Atlas found about the company

Type: prototype (HITL)
Status: resolved
Blocked by: 08

## Question

The Company dossier for a reader: it opens with what Atlas found about the company (its supply-chain layer; the Hypotheses or research questions it appears in; its reviewed Relationships written as plain sentences with the quote behind each, `approved` and `machine_reviewed` distinguished; open questions about it), and folds the records (identity, listings, financials, sources with ticket 04's chips, the memory strip) under "Records". Two or three variants on Lumentum's real dossier, in ticket 08's visual language. The answer is the layout ticket 05 builds.

## Answer

**Variant A, findings first** (the owner, 2026-10-06), with C's key facts folded into the line under the name (ticker · country · layer). Captured with B (through the thesis's steps) and C (a key-facts column) on the throwaway branch `prototype/reader-dossier` (commit `246e363`; `/company/?id=<lumentum>&reader=A|B|C`), fed by Lumentum's real Relationships.

The page: the kicker (layer · theme · ticker); the name; **Atlas's one-line view of the company** (hand-written in the prototype: Atlas must produce it); **In the research**: a card per Hypothesis the company appears in, with its part in the argument (which steps its evidence supports); **What Atlas found**: plain sentences from its Relationships grouped as Constraint and demand, Capacity, Supply chain, What it makes, each with its review state (Approved, Machine-reviewed, Awaiting review; rejected ones hidden) and the quote on click; **Records** folded at the bottom (the existing dossier: identity, listings, Relationships table, financials, sources with ticket 04's chips, the memory strip).

Seen on real data: Lumentum's three constraint statements all await review; its approved findings are capacity and products. The reader's trust depends on the review step.

The owner then added (2026-10-06): the thesis is primary; second comes **the sourcing of the company believed to be well positioned**, per the Serenity method. That shapes the reader page further (ticket 11).
