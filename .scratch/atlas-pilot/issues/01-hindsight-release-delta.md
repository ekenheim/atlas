# Hindsight releases after 0.10.1: anything Phase 2 needs?

Type: research
Status: resolved
Blocked by: none

## Question

Between Hindsight 0.10.1 and the latest release, which changes affect the Phase 2 gate? Look specifically at bank templates, document versioning and document_id upsert semantics, strict tag matching, reflect structured output and provenance, the operations API, mental models, knowledge pages, export/import, and any breaking API or migration changes. Is there a concrete reason to pin something other than 0.10.1 for the dedicated Atlas release?

Primary sources: GitHub releases/changelog for vectorize-io/hindsight, the docs at hindsight.vectorize.io, and the source code at the relevant tags.

## Context

Research in progress on branch `research/hindsight-release-delta`; findings in `docs/research/hindsight-release-delta.md` on that branch.

## Answer

**Keep 0.10.1.** It is still the latest release (2026-09-21), and GHCR has no newer image. The only newer code is unreleased commits on `main`. All nine matrix features exist in 0.10.1; every Phase 2 gate item is achievable with workarounds. The upgrade candidate is the next release that contains commits `6786420d`, `878f4399`, `30321682` and `f4f6b154`.

What this means for later tickets:

- **Replace upsert is a chunk-level delta**, not the full delete-and-re-extract the docs describe; changed chunks still lose their old facts. Per-version `srcv:<sha256>` document IDs stay mandatory. Ticket 06 must verify this live.
- **Reflect provenance is thin:** cited memories carry only an id and text, so every citation needs a `GET /memories/{id}` to reach its `document_id`. Structured output is a second, loosely enforced LLM pass, so Atlas validates it. This feeds ticket 07.
- **Two operational risks are fixed only on `main`:**
  - mental-model refresh loops that burn spend (issue #4532);
  - trickling LLM streams pinning worker slots in `processing` (issue #4763).

  Mitigations: explicit or cron refresh with a minimum interval, the LiteLLM budget, and operation outcomes decided on `status` only. This feeds ticket 07.
- **Not verified:** the next release date; whether a failing `refresh_after_consolidation` also loops; whether a LiteLLM timeout prevents the slot hang. All findings come from code, docs and issues, not a running instance.

Full findings: `docs/research/hindsight-release-delta.md` on branch `research/hindsight-release-delta` (`61101e1`).
