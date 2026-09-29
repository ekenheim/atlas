# 05: FCA National Storage Mechanism adapter (IQE)

**What to build:** IQE's regulatory announcements and annual reports are ingested from the FCA National Storage Mechanism (NSM), with the same guarantees as the exchange ingest path built in ticket 04. The terms check (2026-09-29, `docs/decisions.md`) found:
- LSE RNS is not allowed: its robots.txt disallows `/en-gb/`, and its disclaimer restricts storage to personal, off-network use.
- IQE's own regulatory-news iframe (polaris.brighterir.com) disallows all robots.
- The NSM terms allow use "for any lawful purpose" subject to the Acceptable Use Policy: no disruption, and no reproducing or reselling the site. The NSM has no robots.txt and offers CSV export of search results with per-line download links.

Spec: `.scratch/atlas-phase3-6a/spec.md`. Terms sources: https://data.fca.org.uk/artefacts/NSM_Terms_of_Use.pdf, https://data.fca.org.uk/artefacts/NSM_General_AUP.pdf, https://www.fca.org.uk/publication/primary-market/nsm-investor-user-guide.pdf

**Blocked by:** 04 (the exchange ingest path)

**Status:** done

- [x] NSM adapter tested from hand-written fixtures in the documented shapes (marked as such); low, fixed request rate; the terms gate recorded per fetch.
- [x] `available_at` uses the NSM's publication/submission timestamp (basis `publisher_timestamp`), else observed discovery.
- [x] An IQE results announcement or annual report fixture is ingested, parsed (PDF) and retained.
- [x] `source_path` for IQE becomes `exchange:fca-nsm`; LSE RNS is recorded as a blocked source.
