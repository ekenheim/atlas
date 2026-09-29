# available_at must respect EDGAR's after-hours dissemination

Type: task
Status: open
Blocked by: none

## Question

Phase 1 sets `available_at = acceptanceDateTime` (basis `sec_acceptance`). EDGAR disseminates filings accepted after 17:30 ET (and on weekends/holidays) on the next business day, so for those filings the public-availability time is later than acceptance. That understates `available_at` and breaks spec §9's conservative rule. It affects ingest, as-of views and replay cutoffs.

Fix, test-first:
- compute `available_at` as the EDGAR dissemination time (acceptance time if within the filing window on a business day; otherwise the next business day's opening), with a new basis `sec_dissemination`
- keep `acceptanceDateTime` in metadata
- cite SEC's filer manual / EDGAR operating hours and holiday calendar
- decide how existing Source Versions are handled (they're immutable: a recorded correction, not an edit)

Record the decision in `docs/decisions.md`.
