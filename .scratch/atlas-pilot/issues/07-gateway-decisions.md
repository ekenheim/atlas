# Hindsight gateway and bank-policy decisions from the matrix

Type: grilling
Status: resolved
Blocked by: 06

## Question

With the matrix in hand, decide:

- the document_id scheme per Source Version
- the tag vocabulary, and strict-matching usage
- the bank configuration mechanism (template import vs the config API)
- how the returned facts are mapped to Source Versions, and what happens when that mapping is unavailable
- the retain granularity (whole parse vs bounded sections with anchors)
- operation polling and zero-fact handling
- which two mental models ship in Phase 2

Inputs from ticket 01 to weigh:

- reflect citations need a per-memory lookup to reach `document_id`
- structured output is loosely enforced
- the mental-model refresh-loop risk (#4532)
- the worker-slot hang (#4763)

Record spec deviations in `docs/decisions.md`.

**Inputs from ticket 06 (`docs/hindsight-feature-matrix.md`):**

- two-hop provenance via `source_memory_ids` and preserved `metadata.source_version_id`
- chunk-sourced reflect content can't be resolved to a memory
- templates exist (so use a versioned template, not the config API)
- strict tag modes work
- one operation per batch retain
- the alternative listing routes
- no union types in schemas

**Input from ticket 12:** the candidate glossary term *Bottleneck* (a constrained input with no qualified second source or substitute in the relevant timeframe, where the owner has pricing power), and the proposed wording for the Bottlenecks mental model. Both are in `docs/research/serenity-skills-alignment.md`.

## Answer

Grilled 2026-09-28, all recommendations accepted:

7. **Document IDs:** `srcv:<source_version_uuid>:<section-anchor>`. A Source Version whose raw hash is already retained is linked, not re-retained. See `docs/adr/0001-hindsight-document-id-per-source-version.md`.
8. **Granularity:** one retain item per filing section, submitted as one batch per Source Version. The metadata carries `source_version_id`, the anchor and character offsets.
9. **Tags:** `company:<canonical-uuid>`, `theme:<slug>`, `source:<provider>`, `doctype:<kind>`, `form:<form>`. The gateway uses only `any_strict` / `all_strict` and rejects `any`.
10. **Bank configuration:** a versioned template file in the repo, applied on deploy (dry run first, then for real), with its version recorded per run.
11. **Citation states:**
    - **resolved:** two-hop resolution reaches a Source Version and the quote validates against the archived parse. Only these count as Evidence.
    - **unverified:** the text came from a raw chunk with no memory ID, or the quote doesn't match.
    - **broken:** a cited memory has been deleted.
12. **Operations:**
    - outcomes are decided by `status` only, with a polling timeout
    - after completion, memories are counted per `document_id`
    - a zero-fact section gets one reprocess, then is marked `zero_fact`
13. **Mental models:**
    - Phase 2 ships **Theme status** and **Bottlenecks** (worded with ticket 12's test)
    - both refresh daily on a cron with `min_refresh_interval_seconds`, and `refresh_after_consolidation` stays off (#4532)
    - no knowledge pages in Phase 2
14. **Glossary:** **Bottleneck** was added to `CONTEXT.md`.
