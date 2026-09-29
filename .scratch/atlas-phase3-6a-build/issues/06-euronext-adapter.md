# 06: AMF info-financière adapter (Soitec)

**What to build:** Soitec's regulated information is ingested from the AMF's open info-financière API, with the same guarantees as the exchange ingest path built in ticket 04. The terms check (2026-09-29, `docs/decisions.md`) found:
- Euronext is not allowed: its terms prohibit spiders and robots and systematic retrieval, and its robots.txt blocks AI bots from company news.
- soitec.com forbids reuse without written permission.
- info-financiere.gouv.fr is under Licence Ouverte / etalab-2.0, and its documented API allows 10,000 calls per IP per day at `https://www.info-financiere.gouv.fr/api/explore/v2.0`. Its robots.txt disallows `/api/` for crawlers; Atlas is an API client, not a crawler, and never crawls HTML or RSS.

Spec: `.scratch/atlas-phase3-6a/spec.md`. Terms sources: https://www.data.gouv.fr/dataservices/api-info-financiere, https://www.euronext.com/en/terms-use

**Blocked by:** 04 (the exchange ingest path)

**Status:** done

- [x] Adapter on the documented API only, tested from hand-written fixtures in the documented shapes (marked as such); a fixed low rate far under 10k/day; the Etalab source credited in the stored metadata.
- [x] `available_at` uses the AMF publication timestamp (basis `publisher_timestamp`).
- [x] A Soitec annual report or results fixture is ingested and parsed. French-only documents are archived with `language=fr` and not retained (ticket 03); English versions are retained.
- [x] `source_path` for Soitec becomes `exchange:amf`; Euronext is recorded as a blocked source.
