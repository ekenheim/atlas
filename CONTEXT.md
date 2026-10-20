# Atlas Research

An evidence-driven investment research platform: it discovers industry bottlenecks, maps exposed companies through source-backed evidence, and freezes falsifiable hypotheses for later evaluation. It researches; it never trades.

## Language

### Sources and evidence

**Source Document**:
The stable identity of a piece of source material (a URL, or an SEC accession), independent of any particular copy.
_Avoid_: Document (unqualified), page, filing (when the identity is meant)

**Source Version**:
One immutable, hash-identified copy of a Source Document as fetched at a point in time. Any change to the content is a new Source Version, never an edit.
_Avoid_: Revision, snapshot (reserved for Research Snapshot)

**Fetch Gate Decision**:
Whether Atlas was allowed to request a URL, decided before the request from the site register, the site's terms and its robots.txt, and recorded either way. A blocked source stays visible as a blocked decision instead of silently missing.
_Avoid_: Permission, crawl check

**Claim**:
A statement proposed by an agent or extractor that has not yet been validated against a Source Version. Untrusted by default.
_Avoid_: Fact, finding

**Assertion**:
A ledger record binding a statement to one Source Version and an exact quote span, carrying an epistemic type and a review state. A Claim becomes an Assertion only once its span is confirmed in the archived text.
_Avoid_: Claim (once validated), fact

**Evidence**:
Assertions and the Source Versions behind them, when used to support or refute something. Only primary material counts as Evidence.
_Avoid_: Memory, citation (as a synonym)

**Evidence Family**:
A set of Source Versions that are not independent of each other, such as one announcement syndicated across many sites. The family counts as a single witness.
_Avoid_: Duplicate group, cluster

**Memory**:
Anything derived and held by Hindsight: extracted facts, observations, mental models, knowledge pages. Memory can lead to Evidence but is never Evidence itself, and never counts as an independent witness.
_Avoid_: Evidence, knowledge (unqualified)

**Reading pointer**:
A recalled Memory resolved to a section of a Source Version, recorded with the query that recalled it and its rank in that recall. It is Memory used as an index: it says where an investigation should read. The Scout's pointers (the question and its queries) direct the Investigators; the Skeptic's (each bear-checklist item asked about each company the accepted Claims name) direct the Skeptic. Its window in the section is placed by the chunk its fact was extracted from, when that chunk is found verbatim there (`placed_by` `chunk`), else by the window its Memory text matches best (`match`). It is never Evidence, never quoted, never a witness, and never sent to a role as a statement.
_Avoid_: Recall hit, citation, lead (a lead is a web or filing-search result)

**Entity pointer**:
A reading pointer made by the entity hop rather than a recall: a fact in Memory that carries a company's entity (its canonical name, as its documents and other companies' send it), from another company's document, resolved to that document's section. It names the company whose document it is and the company it was found for, and has its own channel in passage selection and its own weight in the ranking of companies. A co-mention is a reason to read: never an edge, never Evidence, never quoted, never sent to a role.
_Avoid_: Mention, co-mention edge, entity link

### Research objects

**Bottleneck**:
An input, process or capacity that cannot meet demand within the relevant timeframe because no qualified second source or substitute exists, giving its holder pricing power. It is a claim that needs Evidence, not a conclusion drawn from demand growth alone.
_Avoid_: Shortage, chokepoint, constraint (as a synonym)

**Candidate**:
A (company, theme) pair under investigation, with its own lifecycle from lead to rejected or closed. Kept even when rejected, so evaluation isn't winner-only. A Candidate may produce zero or more Hypotheses.
_Avoid_: Idea, pick, opportunity

**Counterparty**:
A company outside the universe that an accepted quote names, kept only so a Relationship has its other end (a customer, a supplier, an owner). It has an identity resolved from a registry and nothing else: it is never ingested, never an investigation seed and in no theme. The owner promotes it to a researched company by adding it to the theme config or committing its Candidate.
_Avoid_: Candidate (a Candidate is under investigation), universe company, external company, third party

**Hypothesis**:
A versioned, falsifiable research object: statement, mechanism, predictions, catalysts, falsifiers and alternative explanations. A published version is immutable; a correction is a new version.
_Avoid_: Thesis (as a standalone noun), idea, call

**Exposure**:
A company's position relative to a Hypothesis's Bottleneck (it holds the scarce capacity, supplies it, or depends on it), with the Evidence of how well it can capture the scarcity: whether second sources or qualified substitutes exist, whether customers have qualified it, pricing power rather than volume, its share of the downstream bill of materials, and its financing (dilution counts against it). A Hypothesis lists its Exposures; each is shown as evidence per test, never as a rating or a recommendation.
_Avoid_: Pick, beneficiary, play, conviction

**Thesis Statement**:
The one-sentence claim at the head of a Hypothesis. It is a field of a Hypothesis, not a separate object.
_Avoid_: Thesis

**Relationship**:
A reviewed, typed, directed edge between companies (and optionally a product or theme), drawn from a fixed predicate whitelist and backed by Assertions. When the object is a product, material or technology, the edge runs from the company to that product node. It is identified by its subject, predicate and object, and carries a supply-chain layer only when its Evidence names one: an ownership stake or a company-level capacity statement has none. One kind of edge has no object at all: a company's own `capacity_constrained` statement that names no product (company-level; one such edge per company, never with a layer).
_Avoid_: Link, connection, edge (outside the UI)

**Bottleneck Predicate**:
One of four whitelisted predicates for a bottleneck fact a company states about itself and a product, with no other company named. Each is directed from the company to the product and needs an exact quote like any other, and the quote must name the particular input or product (generic "materials, components, equipment" is no bottleneck fact); its layer, when the quote names one, is that object's layer:
- `capacity_constrained`: the company cannot fully meet demand for the product (demand exceeds its supply, it allocates, backlogs or is short of it). Growing demand alone is not a constraint, and neither is an expansion plan or an allocation of capital. It alone may be **company-level**: when the company's own document states the constraint of its supply as a whole and names no product ("This demand is outpacing our current supply which has required us to make decisions on supply allocation"), the Claim has no object and no layer, and its Relationship is the company's one company-level edge.
- `sole_sources`: the company gets an input from one supplier or a limited number of suppliers, named or not. A named supplier is `depends_on` or `buys_from` instead.
- `vertically_integrates`: the company makes an input for its own products instead of buying it (in-house, captive, "our own"). Making what it sells is `manufactures`.
- `qualified_for`: customers have qualified the company, or chosen it in a design win, as a supplier of the product. A named customer is `supplies` instead.
_Avoid_: Company attribute, flag, constraint (as a synonym for `capacity_constrained`)

**Counterevidence**:
What the Skeptic finds in archived Source Versions that weighs against an investigation's result. Each accepted item is an Assertion with an exact quote span and is one of two kinds, never both. A **contradiction** names a Claim and denies, limits or dates its statement, about the same company and object; only a contradiction marks a finding contradicted, and it is independent only when it comes from an Evidence Family none of the supporting Claims use. Everything else is Bear Context. A lead, Memory or another role's output is never counterevidence.
_Avoid_: Rebuttal, negative evidence, contradiction (for an item that names no Claim)

**Bear Context**:
Counterevidence that contradicts no Claim: a bear-checklist fact about a company (customer concentration, inventories, dilution and financing, second sources, substitutes, capacity additions) with its quote span. It is shown beside the findings in its own section of the research card, marks no finding contradicted, and never sends an investigation to review.
_Avoid_: Contradiction, risk factor, bear case (the bear case is contradictions and bear context together)

**Research Snapshot**:
An immutable, dated record of exactly what was considered and concluded at a decision time, including the Memory text as it was returned. It is the only exact mechanism for reproducing past beliefs.
_Avoid_: Backup, export, replay

**Belief**:
One falsifiable proposition about a Bottleneck or a company's Exposure, stated in Atlas's words, with an author's judgement (`proven`, `disproven`, `unproven`, `undecidable`), a confidence and an as-of time. It cites Facts (and Assertions) with a signed valence and a weight (load-bearing or context) and nothing else. Its judgement is set only by an author, never computed; it is superseded without loss, and flagged by code, never silently changed, when a cited Fact's document is revised or a load-bearing Fact against it stands.
_Avoid_: Finding, conclusion, claim (a Claim is the Investigator's proposed statement)

**Issue**:
A research question still to answer, kept as scheduled work: it narrows into finer Issues (a bottleneck question into its argument steps, a step into what it needs) and requires others before it can be worked. The next one to work is chosen by rule. It produces Beliefs and Facts.
_Avoid_: Task (an investigation's task is a job of the pipeline), question (unqualified), ticket

**Research Session**:
One run of a researcher on a question as of a time, recorded with what it searched, recorded, proposed and spent, and closed with its card. A Claude session and the pipeline's argument plan are both Research Sessions; an investigation is the pipeline's kind of one.
_Avoid_: Investigation (for a session in general), run (a run is the job queue's record), chat

**Proposed Update**:
A flag on a Hypothesis (and the Candidates it concerns) that later Evidence contradicts what a published version depends on, listing that Evidence. The owner accepts it, which starts a correction, or dismisses it with a reason. The published version and its Research Snapshot never change.
_Avoid_: Amendment, alert

**Replay Bank**:
An isolated Hindsight bank populated only with material available before a cutoff, used to evaluate the pipeline. It does not reproduce a past run.
_Avoid_: Historical bank, backtest

### The record of the scheduled research

**Edition**:
One page a scheduled task published, as Atlas read it on a day: the theme (or the council), the as-of day, the edition number, the page's bytes in the archive and its parsed ledger. Editions are kept insert-only; the same bytes again change nothing, and a page that does not parse is kept with its error.
_Avoid_: Version (a Source Version is a document's copy), snapshot (a Research Snapshot is a published Hypothesis's), report, run

**Ledger**:
The machine-readable JSON at the foot of an edition's page: a theme's chokepoints, predictions and primary sources, or the council's board, stacks and predictions. It is what Atlas parses, compares and checks; the page's prose is not.
_Avoid_: Table, board (the Watch's board is the pipeline's), card

**Rewrite**:
A later edition changing what an earlier one said without saying so: a past prediction's text, deadline or range altered, a prediction removed, a chokepoint gone without being killed, an ID reused, a first-seen day moved later, a settled prediction un-settled. Each is recorded insert-only. A same-day edition with other bytes is marked `same_as_of_differs`.
_Avoid_: Update, revision (a Source Version's revision is the publisher's), correction (a Hypothesis's)

**Ledger prediction**:
A dated prediction an edition made, kept the first time its ID is seen in a theme's (or the council's) ledger and never changed. Its state is derived, never stored: `open` before its deadline, `lapsed` after it with no settlement, `met` or `missed` once a later edition settles it (a settlement is kept insert-only, the first one only).
_Avoid_: Prediction (unqualified: a Hypothesis's prediction is another record), forecast, call (a call is Atlas's own dated claim, priced against closes)

**Quote check**:
The result for one (URL, quote) pair of a ledger's primary sources: the URL fetched once through the fetch gate and archived, the quote located in the parsed text with the typographic fold, and one outcome: `verified`, `not_found` (the page was read and the quote is not in it) or `unreachable` (with the reason), beside the source's tier. A quote verified in a third party's transcript is verified against that transcript, not the company's own words.
_Avoid_: Verification (unqualified), fact check, Assertion (an Assertion is Atlas's own ledger record)

**Drop box**:
The private GitHub repository through which the editions reach Atlas, which stays on the LAN. A collector task writes each page and its extracted ledger to it through its connector, and Atlas pulls it outbound with a read-only token. Git's history is a second copy a later edition cannot rewrite.
_Avoid_: Inbox, relay, webhook
