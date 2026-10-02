# 30: A scenario input is sourced only from the metric and period it means

**What to build:** A sourced scenario input must come from an observation of the metric the input is (revenue from a revenue concept, cash from a cash concept, debt from both debt parts, shares from a share count) and of the period the table is for. Today a cash observation copied into `reported_revenue` passes the currency and value checks.

Evidence: an external review by Codex (the owner shared it on 2026-10-02); the lead verified the finding in the code before writing this ticket; `backend/atlas/scenarios/sources.py` checks that an observation is the company's as-of observation, its currency and its value, not which metric it is. Investigation 1's Financial Analyst also gave Coherent a `total_debt` whose value and basis disagree (pilot-fix ticket 28).

- Each scenario input names the canonical metrics (`configs/financials/metrics.yaml`) that may source it; an observation of another metric is refused with `metric_mismatch`.
- The period: an annual flow input takes a fiscal-year observation, a balance input the latest balance-sheet date at or before the as-of time; anything else `period_mismatch`.
- `total_debt` sourced is the sum of its current and noncurrent parts' observations of one balance date, or estimated with that basis.

**Blocked by:** None

**Status:** needs-triage (waits for the verdict: scenarios are not in the verdict's measures, and the Hypothesis it serves is narrowed by the verdict)

- [ ] The decision in `docs/decisions.md`, "Scenarios", with this case as the evidence.
- [ ] At the scenario seam: a cash observation offered as `reported_revenue` is refused `metric_mismatch`; a quarterly observation offered for an annual input is refused `period_mismatch`.
