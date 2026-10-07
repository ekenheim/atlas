# 01: Archive term search as a service

**Status:** ready-for-agent
**Type:** task

**What to build:** the archive's term search (BM25 over passages, `atlas.evaluation.baseline.search`, today run only by `scripts/pilot_baseline.py` over the API) as a server-side service the reading agent (ticket 03) calls: given a query, a set of companies and an as-of time, the best passages of those companies' parsed, English Source Versions available at the as-of time (filings and call transcripts alike), each with its Source Version, section anchor, character offsets in the current parse, the document's title, kind and `available_at`, and the BM25 score; at most `per_document` passages from one document; near-duplicate paragraphs across filings merged as the baseline does (`also_in`).

Why: in the 2026-10-07 verdict a plain term search of the archive found the on-question passages the investigations missed (baseline coverage 22%), and the researchers' best facts came from call transcripts Atlas already archives (`docs/pilot-report.md`).

**Acceptance:**
- [ ] `atlas.research.search` (or a name in `CONTEXT.md`'s terms) with a function taking `(engine, archive, query, company_ids, as_of, top, per_document)` and returning the hits; passages and their tokens cached per Source Version parse so a second query over the same companies does not re-read the archive (an in-process LRU is enough; say its bound).
- [ ] `GET /api/v1/archive-search?q=&company_id=...&as_of=&top=&per_document=` returns the same hits (read-only), for the workbench and for debugging.
- [ ] Offsets are the current parse's (`parser_version` named in each hit), so a quote taken from a hit passes `check_quote` at those offsets.
- [ ] Tests: integration (API, real Postgres, fixture filings): a term in one company's filing and not another's is found only with that company; `as_of` excludes a later version; duplicates merge; offsets round-trip through the span check. `scripts/pilot_baseline.py` keeps working (it may call the shared function).
