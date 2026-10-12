# 19: The prospective record

Type: build
Status: open
Blocked by: 14

## What to build

A published Hypothesis's `measurable_predictions` become rows: measure, expected range, deadline, settling source (a Fact, an XBRL observation, or a TradingView price under 16b's rules), each with its state (`open`, `settled`, `lapsed`) and its settlement appended, never rewritten; rejected and lapsed Hypotheses kept and listed. `POST /api/v1/hypotheses/{id}/predictions`, `POST .../predictions/{id}/settle`, the dossier page's predictions section.

## Acceptance criteria

- [ ] API tests and the dossier e2e; one prediction recorded on the photonics Hypothesis (the lead).
