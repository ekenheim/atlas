"""A step is disputed only by a confirmed contradiction (pilot-review T3).

Seam: `build_steps`, the pure rule the argument Editor's task decides each step's status by,
over Fact rows shaped as `argument_facts` reads them and the counter-judge's relations as the
Skeptic task records them. On the four 0.5.3 cards 14 of 24 steps were `disputed` though none
of the Skeptic's 50 Facts denied, limited or dated what it was filed against.
"""

import uuid
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import RowMapping

from atlas.investigations.argument import (
    ArgumentFacts,
    KeptStatement,
    StepStatement,
    build_steps,
)
from atlas.investigations.model import CardArgumentStep

COMPANY = uuid.UUID("00000000-0000-0000-0000-00000000c0c0")
VERSION = uuid.UUID("00000000-0000-0000-0000-0000000000f1")


def fact(step: str, statement: str, quote: str) -> RowMapping:
    """A Fact row as `argument_facts` reads it."""
    row: dict[str, Any] = {
        "id": uuid.uuid4(),
        "assertion_id": None,
        "step": step,
        "value_json": {"statement": statement, "status": "in_effect", "period": "2026"},
        "subject_company_id": COMPANY,
        "subject_name": "Vantor Photonics",
        "subject_slug": "vantor",
        "quote": quote,
        "source_version_id": VERSION,
        "span_start": 0,
        "span_end": len(quote),
        "verification_status": "verified",
        "source_title": "Vantor 10-K",
        "available_at": datetime(2026, 9, 1, tzinfo=UTC),
    }
    row["assertion_id"] = row["id"]
    return cast(RowMapping, row)


CONTROL = fact("control", "Vantor is the sole qualified supplier.", "We are the sole supplier.")
RELIEF = fact("relief", "Vantor plans a second fab.", "We plan a second fab.")
COUNTER = fact("control", "Halden is qualifying its line.", "Halden is qualifying its line.")


def steps(relation: str | None, *, against: uuid.UUID | None = None) -> dict[str, CardArgumentStep]:
    """The steps of an argument with a Control and a Relief Fact, each with a kept statement,
    and one Skeptic Fact filed under Control challenging `against` (default: the Control Fact)
    with `relation` (None: no relation recorded)."""
    challenged = against or CONTROL["id"]
    facts = ArgumentFacts(
        sessions=[],
        supporting=[CONTROL, RELIEF],
        counter=[COUNTER],
        against={COUNTER["id"]: [challenged]},
        relations={} if relation is None else {COUNTER["id"]: {challenged: relation}},
        reasons={} if relation is None else {COUNTER["id"]: {challenged: f"k1 {relation} f1"}},
    )
    refs = {"c1": CONTROL, "c2": RELIEF, "c3": COUNTER}
    statements = {
        "control": StepStatement(
            kept=[KeptStatement("Vantor is the sole qualified supplier.", ["c1", "c3"], True)],
            editor_status="supported",
            unchecked=[],
        ),
        "relief": StepStatement(
            kept=[KeptStatement("Vantor plans a second fab.", ["c2"], True)],
            editor_status="supported",
            unchecked=[],
        ),
    }
    built = build_steps(
        facts, statements, refs, skeptic_checked={CONTROL["id"], RELIEF["id"]}, skeptic_ran=True
    )
    return {step.step: step for step in built}


def test_a_counter_fact_that_only_qualifies_leaves_the_step_supported() -> None:
    control = steps("qualifies")["control"]

    assert (control.status, control.contested) == ("supported", False)
    [shown] = control.counterevidence
    assert shown.fact_id == COUNTER["id"]
    assert shown.against == []
    assert [(r.fact_id, r.relation, r.reason) for r in shown.relations] == [
        (CONTROL["id"], "qualifies", "k1 qualifies f1")
    ]
    # The statement citing it carries it with its relation too.
    [said] = control.statements
    assert [(c.fact_id, c.against) for c in said.counterevidence] == [(COUNTER["id"], [])]
    assert [r.relation for r in said.counterevidence[0].relations] == ["qualifies"]
    assert not any("could not be judged" in note for note in control.unchecked)


def test_a_counter_fact_that_contradicts_a_fact_of_the_step_disputes_it() -> None:
    control = steps("contradicts")["control"]

    assert (control.status, control.contested) == ("disputed", True)
    [shown] = control.counterevidence
    assert shown.against == [CONTROL["id"]]
    assert [r.relation for r in shown.relations] == ["contradicts"]


def test_limits_and_dates_dispute_as_contradicts_does() -> None:
    assert steps("limits")["control"].status == "disputed"
    assert steps("dates")["control"].status == "disputed"
    assert steps("supports")["control"].status == "supported"
    assert steps("unrelated")["control"].status == "supported"


def test_an_unjudged_relation_still_disputes_and_says_so() -> None:
    for relation in ("unjudged", None):
        control = steps(relation)["control"]

        assert (control.status, control.contested) == ("disputed", False)
        [shown] = control.counterevidence
        assert shown.against == [CONTROL["id"]]
        assert [r.relation for r in shown.relations] == ["unjudged"]
        assert "1 counter-Fact could not be judged" in control.unchecked


def test_a_counter_fact_filed_under_the_step_against_another_step_s_fact_does_not_dispute_it() -> (
    None
):
    built = steps("contradicts", against=RELIEF["id"])
    control, relief = built["control"], built["relief"]

    # Filed under Control, it is still shown there, but it speaks only against Relief's Fact.
    assert [c.fact_id for c in control.counterevidence] == [COUNTER["id"]]
    assert (control.status, control.contested) == ("supported", False)
    assert (relief.status, relief.contested) == ("disputed", True)
    assert [c.against for c in relief.counterevidence] == [[RELIEF["id"]]]
