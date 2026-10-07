# 02: Facts that hold a quantity, a period and a status

**Status:** done
**Type:** task

**What to build:** a **Fact**: a verbatim quote at an archived span (the Assertion's span check, unchanged) about one company, recorded with the argument step it bears on and, when the quote states them, a quantity, a period or date, and a status. A Fact needs no predicate from the Relationship whitelist: it is an Assertion with predicate `fact` and a validated `value_json`:

- `step`: one of `constraint` (what is constrained, in what units, over what period), `demand_vs_supply`, `relief` (capacity, second source or substitute, and how fast), `control` (who holds the scarce capability), `capture` (how the company earns more from it: pricing, share, financing), `invalidation` (what would disprove the argument), `context`;
- `statement`: the fact in one sentence, in the quote's terms (the reading agent writes it; ticket 04's check judges it);
- `quantity` (optional): `value` (number), `unit`, `metric`; the number must occur in the quote (the grounding check's number rule, `atlas.investigations.grounding`);
- `period` (optional): a date or a range as the quote gives it ("Q3 FY2026", "through 2028", "by the end of calendar 2027");
- `status`: `in_effect`, `planned`, `in_development`, `hedged` (risk or possibility language), `regulatory` (a rule, permit or control in force), `reported_by_third_party`.

Why: in the verdict most of a researcher's facts were magnitudes, shares, timelines and regulatory status (export permits), which the Claim model can't hold (pilot fix 38), and Claims turned hedged or planned language into present fact (pilot fix 35): a status recorded at the source keeps the tense from the start.

**Acceptance:**
- [x] `atlas.facts` (record, read), insert-only and audited like Assertions; `GET /api/v1/facts?company_id=&step=&investigation_id=`, `GET /api/v1/facts/{id}`; the API client regenerated.
- [x] Validation refuses: an unknown step or status; a quantity whose number doesn't occur in the quote; a quote not verbatim at its span (the existing check).
- [x] The Relationship review ignores `fact` Assertions (no edge from a Fact).
- [x] Tests at the API seam (real Postgres, fixture filing): record, read, each refusal.
