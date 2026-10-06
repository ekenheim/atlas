# How fast memory/health and the dossier answer on production

Type: task (AFK)
Status: open
Blocked by: none

## Question

How long do `GET /api/v1/memory/health`, `GET /api/v1/memory/health?company_id=<lumentum>`, `GET /api/v1/companies/{id}/dossier`, `GET /api/v1/queue` and `GET /api/v1/memory/reconciliations?limit=1` take on production (https://atlas.ekenhome.se), median and worst of 5, and how much of `memory/health` is the Hindsight listings (compare a response whose `observation_scopes`/`entities` are `unavailable`, if one occurs, or time the listings' share from the server logs)? Read-only GETs; save one full `memory/health` response as the fixture-shaped sample the prototype (ticket 02) uses, in `.scratch/atlas-frontend/samples/` (gitignored if large).

The answer decides the loading design: under ~1 s, one request and a skeleton; above, bank totals first and the listings blocks as they arrive (Doherty), which may mean asking the lead for a listings-free variant (an API gap, not built here).
