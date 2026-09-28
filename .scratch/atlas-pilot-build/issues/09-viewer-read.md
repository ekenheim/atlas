# 09: Source viewer (read-only)

**What to build:** The researcher can browse a company's Source Documents, version history and full provenance, read the parsed text and download the original bytes, all in the static frontend served by the API. Spec Part A: Frontend, stories 46–48 and 50.

**Blocked by:** 07 (Ingest a Lumentum filing end to end)

**Status:** ready-for-agent

- [ ] The typed API client is generated from the OpenAPI schema
- [ ] The provenance panel shows URL/accession, hashes, every timestamp with its basis, parser version and fetch status
- [ ] A Playwright smoke test opens a Source Version and sees its provenance and parsed text
