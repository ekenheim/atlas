# 05: Counterparty companies outside the theme (customers and suppliers)

**What to build:** Supply-chain edges need both ends. Coherent's supply agreement with NVIDIA couldn't become an edge because NVIDIA isn't in the universe. The same holds for hyperscalers, other suppliers (Sumitomo, Mitsubishi Electric, Broadcom) and equipment makers (Aixtron, Veeco). Add **counterparty companies**: known entities that exist so an edge can have an end, without being researched themselves (no ingest, no investigation seeds). They are created through entity resolution when an Investigator or Reviewer names an unseeded company in an accepted quote. They start as `counterparty` (auto-created, with the identity resolved where possible), and the owner can promote one to a Candidate or a researched company.

**Blocked by:** None

**Status:** ready-for-agent

- [ ] A company role, `researched` or `counterparty`, with a migration. Counterparties are excluded from ingest and seeds, and included in the edge table, the theme map and the dossier.
- [ ] When the Investigator names a known non-universe company (e.g. "NVIDIA"), the extraction resolves it (a deterministic ticker or name match via entity resolution) into a counterparty, so the Claim can become an Assertion with a company object. Tests use a Coherent/NVIDIA fixture.
- [ ] Glossary term (`CONTEXT.md`) and a decision entry.
