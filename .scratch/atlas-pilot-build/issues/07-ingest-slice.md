# 07: Ingest a Lumentum filing end to end

**What to build:** A CLI-enqueued job ingests a configured company's filings into immutable Source Versions with exact provenance, archived raw bytes and a deterministic parse. All of it is browsable through the read API. Lumentum is seeded from config, with a Coherent config stub. Spec Part A: Source ledger, Parser, Schema, API; the Phase 1 gate; stories 25–36.

**Blocked by:** 03 (Audit trail and actor), 04 (Job queue and single-pass worker), 05 (Archive (filesystem + S3)), 06 (SEC EDGAR adapter)

**Status:** done

- [x] Fetching an unchanged filing twice yields exactly one Source Version; a changed fixture yields a new Source Version linked via supersedes
- [x] `available_at` equals the fixture's `acceptanceDateTime` with basis `sec_acceptance`; all clocks stay distinct
- [x] Original bytes are retrievable exactly and match `raw_sha256`; the parse is deterministic per parser version
- [x] Every mutation produced an audit event, and the chain verifies
- [x] Company, Source Document/Version and content read endpoints work as specified
