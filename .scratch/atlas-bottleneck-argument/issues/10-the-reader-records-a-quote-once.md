# 10: The Reader records a quote once

**Status:** done
**Type:** bug

**What happened:** on the 0.5.5 pilot, question 2, the same quote was recorded as several Facts. Lumentum's "might not be enough" appeared 3 times and the CHIPS Act funding 3 times. Each copy carried the same mistake: an overstated hedge in the first case, a `regulatory` status in the second. So 6 of question 2's 14 wrong Facts are two errors, counted three times each. Duplicates also inflate the Facts the Editor and the judges read, and the tokens.

**What to build:** before a Fact is recorded, look for an existing Fact of the same investigation with the same Source Version and an overlapping span (or the same quote, folded). If one exists, don't record a second one: return the existing Fact's id to the Reader as "already recorded" (with its step), and let a different step reuse it rather than duplicate it. Count the skipped duplicates in the Reader's artifacts.

**Acceptance:**
- [x] A unit or integration test: the same span recorded twice, by the same Reader or by two Readers, gives one Fact. (`tests/integration/test_reader.py::test_the_same_span_recorded_twice_by_one_reader_gives_one_fact_and_the_reader_is_told_its_ref`, `tests/integration/test_argument_plan.py::test_a_span_two_readers_record_is_one_fact_listed_for_both_steps`; the rule in `tests/unit/test_fact_duplicates.py`.)
- [x] Measured offline on the saved 0.5.3, 0.5.4 and 0.5.5 Facts: how many duplicates by span each question had. (`.scratch/tools/fact_duplicates.py`, replaying `atlas.facts.duplicates.duplicate_of`; per question in `docs/implementation-log.md`, "One Fact per span".)

**Answer (2026-10-08):** the rule is "the same span or folded quote, any step" or "an overlapping span with the same status and an alike statement" (`docs/decisions.md`, "One Fact per span"). The session's own duplicate is refused with its reference; another Reader's is reused for the step (one row, listed under both steps); the argument Skeptic is refused a Reader's Fact.
