# 18: Bottleneck signals across the universe

Type: build
Status: open
Blocked by: 16

## What to build

`atlas.discovery` over the archive: a nightly scan (`scan_signals` job, no LLM) of newly ingested sections for the Serenity cues (`configs/discovery/signals.yaml`: the early-signal case studies' phrases and the Reader's constraint vocabulary, weighted), each hit a `lead` of origin `archive_signal` with its quote, span, company and score; `GET /api/v1/leads?origin=archive_signal` ranked; the Scout prompt reads the ranked leads first. EDGAR full-text search and SearXNG stay the web channels.

## Acceptance criteria

- [ ] Worker tests on the fixtures; the AXT replay: the scan over documents available by 2025-08-31 ranks the 31 July 2025 sentence in its top five (recorded in `docs/experiments.md`).
