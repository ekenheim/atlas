# available_at must respect EDGAR's after-hours dissemination

Type: task
Status: done
Blocked by: none

## Question

Phase 1 sets `available_at = acceptanceDateTime` (basis `sec_acceptance`). EDGAR disseminates filings accepted after 17:30 ET (and on weekends/holidays) on the next business day, so for those filings the public-availability time is later than acceptance. That understates `available_at` and breaks spec §9's conservative rule. It affects ingest, as-of views and replay cutoffs.

Fix, test-first:
- [x] compute `available_at` as the EDGAR dissemination time (acceptance time if within the filing window on a business day; otherwise the next business day's opening), with a new basis `sec_dissemination`
- [x] keep `acceptanceDateTime` in metadata
- [x] cite SEC's filer manual / EDGAR operating hours and holiday calendar
- [x] decide how existing Source Versions are handled (they're immutable: a recorded correction, not an edit)

Record the decision in `docs/decisions.md`.

## Answer

Done (see `docs/decisions.md`, 2026-09-29 "EDGAR dissemination time", and the implementation log). Accepted 06:00–17:30 ET on an EDGAR business day → acceptance (basis `sec_acceptance`); otherwise 06:00 ET on the next business day (basis `sec_dissemination`, only when it differs). Ownership-type forms use 22:00 ET. Explicit holiday table 2019–2027 in `backend/atlas/sources/edgar_calendar.py`; outside it, `EdgarCalendarRangeError`. Existing versions get an append-only, audited `source_version_availability_correction` via `atlas ledger correct-availability`; readers use the `source_version_availability` view (migration `0012`).
