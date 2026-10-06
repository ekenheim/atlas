# What the dossier and version pages add about coverage and memory

Type: prototype (HITL)
Status: resolved
Blocked by: 03

## Question

On the Company dossier: the Memory block (from `memory/health?company_id=`, the same bar and counts as the company's row on `/memory/`), where it sits among Identity, Listings, Relationships and Financials, and the source list's filter by source type (transcripts among them, by `source_type`/`provider`): chips or a select, counts per type, default. On the version page: what `GET /api/v1/source-versions/{id}/memory` shows (retain state counts, profile against `current_retain_profile`, partial, facts, operations) and where. The answer is the agreed layout, as an asset.

## Answer

**Variant A** (the owner, 2026-10-06), captured with B and C on the throwaway branch `prototype/dossier-memory` (commit `0439749`):
- A one-line Memory strip under the title: the version bar, in memory / total, facts, retired, skipped, the status tag (from the whole bank's `memory/health`, so "thin" is measured against the other companies; a company-scoped call can't tell), and a link to `/memory/`.
- The dossier keeps its order. Source Documents stays last, with type chips (All, Filings, Transcripts, XBRL facts, each with its count) and 25 rows, then "Show all".
- The version page gains a Memory section after Provenance: one line (state, sections, facts, the retain profile, flagged if below the current one) and a "Sections" toggle for the per-section table.
- API gaps for the lead: a Source Document in the dossier has no publication time (only `first_seen_at`, the same week for all), so the list can't run newest first; transcript titles ("Q3 2025") name neither the company nor the date.

**The owner's verdict on the page as a whole (2026-10-06):** "a nightmare to navigate and understand". As an end user the owner wants the direction the research found, and the evidence for Atlas's assessment, not the raw records. That reframes what the build ticket (05) and the landing page (06) are for. See the map.
