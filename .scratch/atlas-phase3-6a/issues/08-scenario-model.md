# The Phase 5 scenario model

Type: grilling
Status: resolved
Blocked by: 04

## Question

Decide:
- the low/base/high model structure (§8.2), including BOM share (ticket 12)
- sourced vs estimated inputs and how each input shows its basis
- the sensitivity output
- how scenarios attach to Hypothesis versions
- what 'recomputes deterministically' means in tests

## Answer

Grilled 2026-09-29; the owner accepted all.

- **Deterministic low/base/high model** (§8.2): units × share × price → revenue × margin → contribution → valuation, plus **BOM share** (ticket 12). Every input is labelled **sourced** (an XBRL fact or Assertion span) or **estimated** (with its basis). Missing inputs are shown as missing, never invented.
- **Financial data:** XBRL as-of by filing availability (tickets 04 and 10: `filing_availability`, never `frame`); per-concept tag precedence; restatement linkage; a suspect flag; Q4 = FY − 9M. Product exposure comes from text Assertions.
- **Scenarios attach to a Hypothesis version**, with ±20% per-input sensitivity. Deterministic recompute (the same inputs give byte-identical output), tested. No PyMC.
