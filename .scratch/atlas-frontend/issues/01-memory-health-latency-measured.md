# How fast memory/health and the dossier answer on production

Type: task (AFK)
Status: resolved
Blocked by: none

## Question

How long do `GET /api/v1/memory/health`, `GET /api/v1/memory/health?company_id=<lumentum>`, `GET /api/v1/companies/{id}/dossier`, `GET /api/v1/queue` and `GET /api/v1/memory/reconciliations?limit=1` take on production (https://atlas.ekenhome.se), median and worst of 5, and how much of `memory/health` is the Hindsight listings (compare a response whose `observation_scopes`/`entities` are `unavailable`, if one occurs, or time the listings' share from the server logs)? Read-only GETs; save one full `memory/health` response as the fixture-shaped sample the prototype (ticket 02) uses, in `.scratch/atlas-frontend/samples/` (gitignored if large).

The answer decides the loading design: under ~1 s, one request and a skeleton; above, bank totals first and the listings blocks as they arrive (Doherty), which may mean asking the lead for a listings-free variant (an API gap, not built here).

## Answer

Measured 2026-10-06 ~15:15 local, 5 GETs each from the owner's PC over the public URL, read-only:

| Read | Median | Worst | Size |
| --- | --- | --- | --- |
| `memory/health` | 0.648 s | 0.910 s | 24 KB |
| `memory/health?company_id=<lumentum>` | 0.448 s | 0.517 s | 3.8 KB |
| `companies/{lumentum}/dossier` | 0.441 s | 0.484 s | **1.08 MB** (financials 963 KB, sources 165 KB, 226 documents) |
| `queue` | 0.039 s | 0.081 s | 2.3 KB |
| `memory/reconciliations?limit=1` | 0.027 s | 0.038 s | 0.5 KB |
| `relationships/exceptions?limit=1` | 0.026 s | 0.035 s | 0.7 KB |

Both listings were `ok` (no `unavailable` response to compare), so the listings' share was not isolated; the whole call stays under 1 s anyway.

**Loading design:** one request per page and a skeleton in the final layout (no progressive blocks, no listings-free variant, no API gap). `/memory/` misses Doherty's 400 ms on the server alone, so the skeleton must show the table's shape at once. On the dossier the Memory block is its own request (`memory/health?company_id=`), fired in parallel and rendered when it lands, never waiting on the 1 MB dossier. The landing page's four signals: queue, reconciliation and exceptions are instant; the gap count rides on `memory/health` (~0.65 s), so it renders after the others.

**Facts for ticket 02**, from the saved sample `.scratch/atlas-frontend/samples/health.json` (also `health_lumentum`, `queue`, `reconciliations`, `exceptions`):
- 12 researched companies; versions 1,196 = 521 in memory, 443 retired, 232 all skipped, 0 gaps; sections 3,556, facts 44,973; reconciliation `clean`.
- **Innolight has 0 versions.** The versions block counts no gap for it, yet it is the biggest hole (HKEX's terms block fetching). The page must show "nothing ingested" as a gap of its own, not as a quiet zero.
- Depth differs more than counts: Lumentum 69 versions in memory, 7,045 facts; IQE 55, 1,322; Soitec 16, 1,139. Facts per company belong in the table.
- Coherent 287 of 354 versions retired, Lumentum 156 of 225: retired is the largest state for both and must read as intended (muted), not as loss.
- A consolidation requested 2026-10-04 is still `processing` after 337 rounds; 2,743 sections retained since the last completed run. That run's age and rounds are a signal.
- The dossier's 1 MB payload (financials) is an existing Doherty cost on that page. It is not this map's to change; it is noted for the lead.
