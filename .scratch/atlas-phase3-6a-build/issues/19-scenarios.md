# 19: Scenarios and Financial Analyst

**What to build:** A deterministic low/base/high scenario per Hypothesis version (units × share × price → revenue × margin → contribution → valuation, including BOM share) on as-of XBRL data and versioned assumptions. Each input is sourced (XBRL fact or Assertion span) or estimated (with basis); missing inputs block their line. ±20% single-input sensitivity; identical inputs give byte-identical outputs. The Financial Analyst role proposes the inputs.

Spec: `.scratch/atlas-phase3-6a/spec.md`.

**Blocked by:** 16 (Hypotheses); 18 (XBRL normalization)

**Status:** done

- [x] Pure scenario function with hashed outputs; unit tests of the math
- [x] Analyst role fills the investigation's Analyst slot
- [x] `hypotheses/{id}/scenarios` API
- [x] Gate tests: byte-identical recompute; no source-free financial figure passes validation
