# Spec: Memory-directed, multi-hop reading

**Status:** ready-for-agent

Decided by the lead on 2026-10-01 under the owner's delegation, after the owner asked whether Atlas uses Hindsight to the maximum, said the MiniMax subscription is dedicated to this project, and told the lead to adjust what needs adjusting. Evidence: pilot investigation 1 on 0.2.5 (`.scratch/pilot/results.md`, "Investigation 1, third run"), the usage map and the recall probe below.

## Problem Statement

A researcher asks Atlas a multi-hop bottleneck question ("who supplies the laser chips, who is constrained, what feedstock limits them?"). The answer is spread over several companies' filings, press releases and investor slides, all archived, and Hindsight has already extracted the facts from them. Atlas barely asks it:

- **Memory is consulted twice, narrowly.** The Scout is sent the Bottlenecks mental model's text, the same whatever the question. Each Investigator makes one recall with the whole multi-clause question, scoped to its one seed company; the answer is reduced to a set of sections, the ranking is thrown away, and no other role recalls anything. Reflect, the Theme status model and theme-wide recall are unused by any role.
- **Only the seed companies are read.** The question about InP feedstock was asked with Coherent and Lumentum as seeds, so AXT's filings were never opened, although AXT is in the universe and its filings state a three-year 6-inch InP substrate supply agreement with Coherent and a backlog of substrate orders waiting for export permits.
- **Reading is dealt out, not aimed.** Every document gets an equal share of 24 passages. Lumentum's 10-K got 3 passages and stopped 2,000 characters short of "This demand is outpacing our current supply which has required us to make decisions on supply allocation", while 8-Ks about officer changes got a passage each.

The recall probe (production, 2026-10-01, no LLM call) shows what Memory answers when asked as the Scout would ask:
- The question, theme scope: 40 generic product-roadmap facts (Coherent 19 sections, Lumentum 15, MACOM 3, IQE 2).
- "InP wafer substrate 6-inch capacity expansion AXT Coherent Sumitomo Electric", theme scope: AXT's Master Development and Supply Agreement with Coherent for 6-inch InP substrates (10-Q and 8-K), and Coherent's InP fabs.
- "indium gallium germanium export controls permits InP substrates", theme scope: AXT's export-permit backlog for InP substrates (10-Q Items 2 and 1A).
- "demand outpacing supply allocation decisions laser chips", Lumentum: the allocation statement in the 10-K and the 10-Q, and "a new record for datacom laser chip orders, including substantial 200G EML orders".

The archive-search baseline says the same from the other side: all 20 of its hits lay in sections recall resolved to, and the card covered 2 of the 10 on-question ones. Memory finds the right sections; the pipeline doesn't read the right windows.

## Solution

An investigation asks Memory first, across the whole theme, with focused questions, and reads what the answers point to:

1. The Scout writes its layer-tagged queries as today. Each query, and the investigation's question, is also asked of Memory with the theme's scope. Every recalled fact that resolves to an archived section becomes a **reading pointer**: this query, this fact, this rank, this Source Version section, this company.
2. The companies the pointers name are read, not only the seeds. A question seeded with Coherent and Lumentum reads AXT's 10-Q when Memory points there. Seeds are where the reading starts, not where it ends.
3. Inside a document, the Investigator reads the windows the pointers and a term search rank highest, instead of an equal share in text order. The window that holds the recalled fact is found by matching the fact's words against the section's windows.
4. Memory still never reaches a role as a statement to quote. A pointer chooses what is read; every Claim is still checked against the archived text it quotes. The card shows, for each document read, why it was read.
5. The Skeptic reads the same way: it asks Memory for each bear-checklist item about the companies the Claims name, and what it finds is recorded as either a contradiction of a named Claim or bear context, never both.
6. The checks that lost right Claims and passed wrong ones in the pilot are fixed in the same release: the filer's own impersonal sentences and slide bullets, typographic characters, the constraint and ownership cues, and layers the quote doesn't name.

## User Stories

1. As a researcher, I want each of the Scout's queries asked of Memory across the theme, so that facts in any universe company's documents can direct the reading.
2. As a researcher, I want an investigation seeded with two companies to read a third company's filing when Memory points there, so that a multi-hop question gets a multi-hop answer.
3. As a researcher, I want to see the reading pointers of an investigation (query, recalled fact, company, document, section), so that I can judge why a document was read.
4. As a researcher, I want the fact text in a pointer labelled as Memory, so that I never mistake it for Evidence.
5. As a researcher, I want the Investigator to read the window that holds the recalled fact, so that the statement Memory found becomes a quoted Claim.
6. As a researcher, I want a long filing to get more passages than an administrative 8-K, so that the reading budget follows relevance.
7. As a researcher, I want a document that Memory doesn't point to still searched for the question's terms, so that filings not yet retained are not invisible.
8. As a researcher, I want each results release and periodic report among the chosen documents to keep at least one passage, so that aimed reading doesn't become tunnel vision.
9. As a researcher, I want the research card's `read` rows to say how each document's passages were selected (pointer, search, entity, lead), so that coverage is auditable.
10. As a researcher, I want a Claim quoted from the filer's own slide or impersonal sentence accepted when the counterparty or product is named and the cue is present, so that "The agreement includes an NVIDIA multi-billion-dollar purchase commitment" is not lost.
11. As a researcher, I want a sentence that names two other companies still to prove nothing about the filer, so that co-mention never becomes a Relationship.
12. As a researcher, I want a quote matched when it differs from the parsed text only by typographic hyphens, quotes or spaces, so that slides are quotable.
13. As a researcher, I want the stored quote to be the archived text at the span, so that an Assertion stays verbatim.
14. As a researcher, I want `capacity_constrained` to need language of constraint, so that an expansion plan is not recorded as a shortage.
15. As a researcher, I want `owns` to run from the holder to the issuer, so that an issuer selling shares is not recorded as owning its investor.
16. As a researcher, I want an edge to carry a layer only when its quote or its named product supports one, so that the theme map doesn't place a company in a layer it isn't in.
17. As the owner, I want a right edge with no layer to be machine-reviewable, so that the exceptions queue holds real exceptions.
18. As a researcher, I want the Skeptic's findings split into contradictions of a named Claim and bear context about a company, so that "contradicted" on a card means contradicted.
19. As a researcher, I want bear context (customer concentration, inventories, dilution, second sources) shown on the card in its own section, so that the bear case is visible without discrediting findings it doesn't touch.
20. As a researcher, I want the Skeptic to read documents every time, chosen by asking Memory about each bear-checklist item, so that its coverage doesn't depend on a model's plan.
21. As the owner, I want a discovery's EDGAR phrases to be specific, so that Candidates are companies of the theme.
22. As the owner, I want what was recalled for an investigation stored with it, so that a published Hypothesis's Research Snapshot can say what Memory returned at the time.
23. As the owner, I want recall's cost visible per investigation (calls, memories, pointers), so that the load on the shared Hindsight is known.
24. As a reviewer of the pilot, I want each accepted Claim to record which selection found its passage, so that what Memory adds over search can be measured.

## Implementation Decisions

- **Reading pointer** is a new glossary term (`CONTEXT.md`): a recalled Memory resolved to a Source Version section, recorded with the query that recalled it. It is Memory used as an index. It is never Evidence, never quoted, never sent to a role as a statement.
- **Pointers are stored**, insert-only, per investigation and round: the query (which Scout query or the question), the recall rank, the memory's id, type and text, the Source Version, section anchor and offsets, the company, and the citation state. Only resolved citations make pointers. The investigation read (`GET /api/v1/investigations/{id}`) returns them; the Research Snapshot of a Hypothesis built on the investigation includes them.
- **The Scout task makes the recalls** after it has its queries: one recall for the question and one per query, scope the investigation's theme, the existing scoped-recall service and provenance resolver, the investigation's as-of time applied to the resolved Source Versions (`available_at` at or before it). Recall makes no LLM call and is not counted against the Codex budget; the number of recalls is bounded by the query budget plus one.
- **The plan grows after the Scout.** Companies are ranked by their pointers (count weighted by rank). Seeds always get an Investigator. Other universe companies (role `researched`, never a counterparty) get one while the company budget has room: a new setting, default 6 Investigators per round. The document budget is shared across them as today.
- **Document choice:** an Investigator takes the Source Versions its company's pointers name, best pointer first, then its latest documents as today, up to its share.
- **Passage selection** replaces the equal deal. Candidate windows per document, each with a score:
  1. pointer windows: for each pointer into the document, the window of the pointed section that best matches the memory's text (term overlap, the baseline's tokenizer), scored by the pointer's rank;
  2. search windows: the document's windows ranked by BM25 against the question and the Scout's queries;
  3. entity-tagged windows, as today;
  4. lead windows, as today, only for a document with none of the above.
  Passages are taken best first across the Investigator's documents, with a floor of one for each periodic report and results release that has a candidate, and a ceiling per document (a setting, default one third of the passage budget). A passage records every selection that chose it (`pointer`, `search`, `entity:<id>`, `recall` is retired, `lead`).
- **The search code is shared.** The tokenizer, passage scoring and BM25 of the archive-search baseline move to a module both the baseline and the extraction use; the baseline script's behaviour is unchanged.
- **Memory is not sent to roles.** The Investigator's request is unchanged apart from which passages it holds. Whether a pointer's fact text helps as a hint is a later experiment with its own measurement.
- **The Skeptic** makes one recall per bear-checklist item for each company the accepted Claims name (theme scope), takes documents and windows from the resulting pointers the same way, and falls back to the latest 10-K and 10-Q only for a company with no pointer. Its plan role call keeps only the web and EDGAR queries. "No Memory is sent or read" becomes "no Memory is sent; Memory chooses what is read".
- **Contradiction or bear context.** A Skeptic item names the Claim it contradicts and says how (denies, limits, dates), about the same company and object; the deterministic check refuses a contradiction whose quote names neither the Claim's subject nor its object. Everything else is bear context: a checklist item, a company, a span. Only contradictions mark a finding and drive `needs_review`. The card gains a bear-context section. Independence stays a property of contradictions.
- **Filer as the unnamed party.** A Claim whose subject or object is the company that filed the document is accepted without that company's name in the quote when the quote is from the filer's own document, names the other party (a company object) or the object product, carries the predicate's cue, and names no other universe or counterparty company that could be the unnamed party. The rule is recorded on the Claim (`party_basis: filer`).
- **Typographic fold.** Quotes are located through a one-to-one character fold (hyphen variants, curly quotes, non-breaking and narrow spaces); the Assertion stores the archived text at the span. `offset_source` gains `folded`.
- **Cues.** `capacity_constrained` needs a constraint cue (shortage, allocation of supply, demand exceeding or outpacing supply, sold out, lead times, unable to meet); "capital allocation" is excluded. `owns` in a sentence of share issuance or purchase takes the holder as subject.
- **Layer.** A Claim's layer is optional. It is kept only when a taxonomy term of that layer occurs in the quote or in the object text; otherwise it is null. A Relationship may have no layer: it shows on the companies' dossiers and the edge table, not on a layer of the theme map. An edge's identity is its subject, predicate and object; Evidence with a different supported layer puts the edge in the exceptions queue with `layer_conflict` instead of making a second edge. The Reviewer answers each check separately (direction, hedge, layer), and an unsupported layer no longer records a failed direction.
- **Filing phrases.** A phrase searched in EDGAR has at least two words or is a product or layer term of the theme's ranking config; a filer becomes a Candidate only when its hit scores above the ranking's keep threshold.
- **Settings:** the company budget, the per-document ceiling. Production's passage and token budgets were raised by configuration on 2026-10-01 (home-ops PR #7174); the defaults in code stay.
- **Schema:** a pointer table; `passage.selected_by` values; Claim `party_basis` and a nullable layer on Claim and Relationship with the identity change; the counterevidence kind (contradiction or bear context). One migration per ticket, chained at integration.
- **Decision entries** in `docs/decisions.md` for: Memory as the reading index (and what stays forbidden), multi-hop Investigators, passage selection, the filer rule, the fold, the layer rule and edge identity, contradiction versus bear context.

## Testing Decisions

- Tests exercise external behaviour at the agreed seams: the investigation through the API and a worker pass, the extraction through the `extract_claims` job, the review through `review_relationships`. Pure ranking and cue functions get unit tests.
- **Prior art:** `tests/integration/test_investigations.py` (the scripted roles, the recorded Hindsight fake's `derive_memories` and strict recalls), `test_claims.py` (the extraction seam with recorded Coherent and Lumentum filings), `test_relationships.py`, `tests/unit/test_archive_baseline.py`, `test_claim_predicates.py`.
- **The pilot's sentences are the fixtures.** Each fix is tested with the sentence that exposed it, from the recorded EDGAR fixtures where they contain it and hand-shaped fragments labelled as such where they don't: the allocation statement, the NVIDIA purchase-commitment sentence, the slide bullets with U+2011, the Coherent expansion sentence, the Lumentum share issuance, "indium phosphide capacity in Sherman, Texas".
- The Hindsight fake derives memories whose text paraphrases a sentence of a recorded filing; a test asserts the window holding that sentence is read, and that a non-seed company with a pointer gets an Investigator.
- No live call in tests. The live measure is the pilot: investigation 1 re-run and investigations 2–5 on the release, each against the verdict criteria and the baseline.

## Out of Scope

- Retaining anything Atlas concludes (Claims, Relationships, cards) into Hindsight: circular citation (`docs/threat-model.md`, T3).
- Sending Memory text to a role, and reflect inside an investigation: both wait for the measurement this release makes possible (reflect also spends the shared Hindsight's Codex budget, which is not the budget that was freed).
- A theme-wide term index over the whole archive (search here ranks windows inside chosen documents).
- Faster or wider retention. Pointers reach only retained sections; the backfill's pace is set by the Codex budget, and that decision is the owner's (`.scratch/atlas-pilot/map.md`, parked).
- Per-theme mental models, the Theme status model in a role, pricing-power predicates, the decisions-first landing page.
- The trading lenses and unlicensed sources the Serenity alignment disregarded.

## Further Notes

- **Serenity alignment** (`.scratch/atlas-pilot/issues/12-serenity-skills-alignment.md`): this is M2, multi-hop mapping ("trace capex, then the hardware bought, then its components, then feedstock, and ask who chokes each layer"), which the alignment mapped to Atlas's core workflow but which the seed-only reading did not deliver. Investor decks and conference slides are sources that method relies on; the filer rule and the fold make them quotable. M10, the bear checklist, becomes bear context.
- **What "maximum use of Hindsight" means here:** Memory as the index across the theme (facts and observations, every Scout query), stored and auditable; not Memory as a witness. The next uses (reflect for a prior-knowledge brief, fact text as a hint, per-theme models) are candidates on the pilot-review map, each needing the pointer record this spec adds to be measured.
- **Coverage caveat:** recall sees only what was retained. `GET /api/v1/ingest-plans` shows each company's retained share; the term search inside chosen documents covers the rest of a chosen document, not unchosen ones.
- Pilot-fix tickets 13–20 (`.scratch/atlas-pilot-fixes/issues/`) hold the evidence for each defect; this spec's tickets supersede them.
