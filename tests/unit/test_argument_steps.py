"""A step is disputed only by a confirmed contradiction (pilot-review T3).

Seam: `build_steps`, the pure rule the argument Editor's task decides each step's status by,
over Fact rows shaped as `argument_facts` reads them and the counter-judge's relations as the
Skeptic task records them. On the four 0.5.3 cards 14 of 24 steps were `disputed` though none
of the Skeptic's 50 Facts denied, limited or dated what it was filed against.
"""

import uuid
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from sqlalchemy import RowMapping

from atlas.investigations.argument import (
    ArgumentFacts,
    ArgumentSession,
    KeptStatement,
    StepStatement,
    build_steps,
)
from atlas.investigations.model import CardArgumentStep
from atlas.investigations.reader import ReaderState

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


# --- the invalidation step (pilot-review R2-03) ---------------------------------------------------
#
# On every reviewed card the invalidation step was `supported` by statements arguing for the
# thesis: 96 of its 211 Facts said sold out, record or leading. Each invalidation Fact is now
# judged against the thesis Facts it would break, and the step is `found`, `nothing_found` or
# `unknown`.

INVALIDATION = fact(
    "invalidation", "Vantor plans to double its capacity.", "We plan to double our capacity."
)
INVALIDATION_STATEMENT = "Vantor plans to double its capacity."


def reader_session(step: str, searches: int) -> ArgumentSession:
    return ArgumentSession(
        task_key=f"reader:{step}",
        round=1,
        role="reader",
        step=step,
        status="done",
        state=ReaderState(
            searches=[{"query": f"{step} query {n}"} for n in range(1, searches + 1)],
            summary="searched for eased lead times and second sources; found none",
        ),
    )


def invalidation_step(
    relation: str | None,
    *,
    searches: int = 1,
    session: bool = True,
    skeptic: str | None = None,
) -> CardArgumentStep:
    """The invalidation step of an argument with a Control Fact (the thesis) and one
    invalidation Fact judged against it with `relation` (None: no label recorded), cited by
    the Editor's one statement of the step; the invalidation Reader made `searches` searches
    (`session` False: there was no invalidation Reader). `skeptic`: the relation of a Skeptic
    Fact challenging the Control Fact."""
    facts = ArgumentFacts(
        sessions=[reader_session("invalidation", searches)] if session else [],
        supporting=[CONTROL, INVALIDATION],
        counter=[COUNTER] if skeptic else [],
        against={COUNTER["id"]: [CONTROL["id"]]} if skeptic else {},
        relations={COUNTER["id"]: {CONTROL["id"]: skeptic}} if skeptic else {},
        invalidation=({} if relation is None else {INVALIDATION["id"]: {CONTROL["id"]: relation}}),
        invalidation_reasons=(
            {} if relation is None else {INVALIDATION["id"]: {CONTROL["id"]: f"k1 {relation}"}}
        ),
    )
    refs = {"c1": CONTROL, "c2": INVALIDATION, "c3": COUNTER}
    statements = {
        "invalidation": StepStatement(
            kept=[KeptStatement(INVALIDATION_STATEMENT, ["c2"], True)],
            editor_status="supported",
            unchecked=[],
        ),
        "control": StepStatement(
            kept=[KeptStatement("Vantor is the sole qualified supplier.", ["c1"], True)],
            editor_status="supported",
            unchecked=[],
        ),
    }
    built = build_steps(
        facts,
        statements,
        refs,
        skeptic_checked={CONTROL["id"], INVALIDATION["id"]},
        skeptic_ran=True,
    )
    return {step.step: step for step in built}["invalidation"]


def test_an_invalidation_fact_judged_to_support_the_argument_leaves_the_step_nothing_found() -> (
    None
):
    for relation in ("supports", "unrelated"):
        step = invalidation_step(relation)

        assert step.status == "nothing_found"
        assert (step.statement, step.statements) == (None, [])
        assert step.editor_status == "supported"
        assert "nothing found against the argument after 1 search" in step.unchecked
        # The Fact is still shown, with what it does to the thesis, against nothing.
        [shown] = step.facts
        assert (shown.fact_id, shown.against) == (INVALIDATION["id"], [])
        assert [(r.fact_id, r.relation) for r in shown.relations] == [(CONTROL["id"], relation)]
        assert step.searched == ["invalidation query 1"]
    assert "nothing found against the argument after 3 searches" in (
        invalidation_step("supports", searches=3).unchecked
    )


@pytest.mark.parametrize("relation", ["contradicts", "limits", "dates", "qualifies"])
def test_an_invalidation_fact_that_contradicts_limits_dates_or_qualifies_a_thesis_fact_makes_the_step_found(  # noqa: E501
    relation: str,
) -> None:
    step = invalidation_step(relation)

    assert step.status == "found"
    assert step.statement == INVALIDATION_STATEMENT
    [said] = step.statements
    [cited] = said.facts
    assert cited.against == [CONTROL["id"]]
    assert [(r.fact_id, r.relation, r.reason) for r in cited.relations] == [
        (CONTROL["id"], relation, f"k1 {relation}")
    ]
    assert [f.against for f in step.facts] == [[CONTROL["id"]]]
    assert not any("could not be judged" in note for note in step.unchecked)


def test_an_unjudged_invalidation_fact_keeps_the_step_found_and_says_so_in_unchecked() -> None:
    for relation in ("unjudged", None):
        step = invalidation_step(relation)

        assert step.status == "found"
        assert step.statement == INVALIDATION_STATEMENT
        assert "1 invalidation Fact could not be judged" in step.unchecked
    # A labelled unjudged pair names the thesis Fact; no label at all names none.
    assert invalidation_step("unjudged").facts[0].against == [CONTROL["id"]]
    assert invalidation_step(None).facts[0].against == []


def test_an_invalidation_reader_that_never_searched_leaves_the_step_unknown() -> None:
    never = invalidation_step("supports", searches=0)
    assert (never.status, never.statement, never.statements) == ("unknown", None, [])
    assert invalidation_step("supports", session=False).status == "unknown"
    # Searched or not, an invalidation Fact that bears against the argument is found.
    assert invalidation_step("qualifies", searches=0).status == "found"


def test_a_skeptic_contradiction_of_a_thesis_fact_also_makes_invalidation_found() -> None:
    step = invalidation_step("supports", skeptic="contradicts")

    assert step.status == "found"
    assert [c.fact_id for c in step.counterevidence] == [COUNTER["id"]]
    assert step.counterevidence[0].against == [CONTROL["id"]]
    # The statement over the Reader's supporting Fact is still dropped.
    assert step.statements == []
    # A Skeptic Fact that only qualifies the thesis, or could not be judged, breaks nothing.
    assert invalidation_step("supports", skeptic="qualifies").status == "nothing_found"
    assert invalidation_step("supports", skeptic="unjudged").status == "nothing_found"


def test_a_fact_reused_by_another_step_counts_for_both_in_build_steps() -> None:
    # One Fact per span (ticket 10): the Control Fact, recorded for control, reused by the
    # capture Reader.
    def built(
        steps_of: dict[uuid.UUID, set[str]], capture: bool = False
    ) -> dict[str, CardArgumentStep]:
        facts = ArgumentFacts(
            sessions=[], supporting=[CONTROL, RELIEF], counter=[], steps_of=steps_of
        )
        said = StepStatement(
            kept=[KeptStatement("Vantor is the sole qualified supplier.", ["c1"], True)],
            editor_status="supported",
            unchecked=[],
        )
        statements = {"control": said, **({"capture": said} if capture else {})}
        steps = build_steps(
            facts,
            statements,
            {"c1": CONTROL, "c2": RELIEF},
            skeptic_checked={CONTROL["id"], RELIEF["id"]},
            skeptic_ran=True,
        )
        return {step.step: step for step in steps}

    reused = {CONTROL["id"]: {"control", "capture"}, RELIEF["id"]: {"relief"}}
    shared = built(reused)

    # Listed under both steps, though no statement cites it under capture.
    assert [f.fact_id for f in shared["control"].facts] == [CONTROL["id"]]
    assert [f.fact_id for f in shared["capture"].facts] == [CONTROL["id"]]
    assert [f.step for f in shared["capture"].facts] == ["control"]  # the recorded step
    assert shared["control"].status == "supported"
    assert shared["capture"].status == "unknown"  # no kept statement
    assert "no Fact was recorded for this step" not in shared["capture"].unchecked
    # Without the reuse, capture has no Fact.
    assert built({})["capture"].facts == []
    # A kept statement citing it under capture: both steps are supported by the one Fact.
    both = built(reused, capture=True)
    assert (both["control"].status, both["capture"].status) == ("supported", "supported")
    assert [f.fact_id for f in both["capture"].facts] == [CONTROL["id"]]
    assert [[f.fact_id for f in s.facts] for s in both["capture"].statements] == [[CONTROL["id"]]]
