"""The question's parts (pilot-review R2-01): code's fallback plan of a question, the rule a
Reader's search is held to (`names_a_part`), what the card says of each part
(`parts_answered`) and the planner's response contract.

Seams: the pure functions of `atlas.investigations.question` and `parts_answered`, and the
planner role's response model (what the caller validates every answer with).
"""

import uuid

import pytest
from pydantic import ValidationError

from atlas.investigations.argument import parts_answered
from atlas.investigations.question import (
    QuestionPart,
    QuestionPlan,
    fallback_plan,
    names_a_part,
    planned,
)
from atlas.roles.question_planner import QUESTION_PLANNER, QuestionPlanDraft

# Pilot question 5 (0.5.3 and 0.5.4's argument runs).
Q5 = (
    "How does coherent-optics and systems demand (DCI, 800ZR) pull on component supply, and"
    " where does it bind?"
)


def test_the_fallback_plan_splits_the_question_into_clauses_with_their_terms() -> None:
    plan = fallback_plan(Q5)

    assert plan.source == "fallback"
    assert plan.step_focus == {}
    assert [part.key for part in plan.parts] == ["part_1", "part_2"]
    # The comma inside the parentheses doesn't split the clause.
    assert plan.parts[0].text == (
        "How does coherent-optics and systems demand (DCI, 800ZR) pull on component supply"
    )
    assert plan.parts[1].text == "and where does it bind?"
    terms = [term for part in plan.parts for term in part.terms]
    for expected in ("coherent-optics", "DCI", "800ZR", "component", "supply", "bind"):
        assert expected in terms
    # Stopwords and words of fewer than three letters are no terms.
    assert not {"How", "does", "and", "on", "where", "it"} & set(terms)
    assert plan.parts[1].terms == ["bind"]


def test_a_short_clause_joins_its_predecessor() -> None:
    plan = fallback_plan("Who supplies InP substrates; and why?")

    [part] = plan.parts
    assert part.text == "Who supplies InP substrates, and why?"
    assert part.terms == ["supplies", "InP", "substrates"]


PLAN = QuestionPlan(
    source="planner",
    parts=[
        QuestionPart(key="zr_demand", text="demand (DCI, 800ZR)", terms=["800ZR", "ZR", "DCI"]),
        QuestionPart(
            key="component_supply",
            text="pull on component supply",
            terms=["tunable laser", "ITLA", "coherent-optics"],
        ),
    ],
)


def test_names_a_part_matches_a_term_as_a_whole_word_case_insensitively() -> None:
    assert names_a_part("800zr backlog", PLAN) == "zr_demand"
    assert names_a_part("tunable lasers allocation", PLAN) == "component_supply"
    assert names_a_part("sold out allocation", PLAN) is None
    # A whole word only: "ZR" is not a term of "AZR".
    assert names_a_part("AZR wafers", PLAN) is None
    # A hyphen and a space are the same.
    assert names_a_part("coherent optics module capacity", PLAN) == "component_supply"
    # The first part (in the plan's order) whose term the query names.
    assert names_a_part("ITLA supply for 800ZR", PLAN) == "zr_demand"


def row(part: str | None) -> tuple[dict[str, object], uuid.UUID]:
    """A Fact's row as `fact_rows` gives it (its `id` and `value_json`), and its ID."""
    value: dict[str, object] = {"step": "constraint", "statement": "s", "status": "in_effect"}
    if part is not None:
        value["part"] = part
    fact_id = uuid.uuid4()
    return {"id": fact_id, "value_json": value}, fact_id


def test_parts_answered_distinguishes_answered_facts_only_and_unanswered() -> None:
    plan = QuestionPlan(
        source="planner",
        parts=[
            *PLAN.parts,
            QuestionPart(key="where_it_binds", text="where does it bind", terms=["bind"]),
        ],
    )
    zr_a, zr_b = row("zr_demand"), row("zr_demand")
    component, background = row("component_supply"), row(None)
    supporting = [zr_a, zr_b, component, background]

    shown = parts_answered(
        plan,
        [each for each, _ in supporting],
        # Two kept statements: one citing a ZR Fact with background, one only background.
        [{zr_a[1], background[1]}, {background[1]}],
    )

    assert [(p.key, p.status, p.facts, p.statements) for p in shown] == [
        ("zr_demand", "answered", 2, 1),
        ("component_supply", "facts_only", 1, 0),
        ("where_it_binds", "unanswered", 0, 0),
    ]
    assert shown[0].text == "demand (DCI, 800ZR)"


def test_the_planner_s_answer_is_bounded_and_its_focus_kept_by_step() -> None:
    assert (
        QUESTION_PLANNER.name,
        QUESTION_PLANNER.prompt.name,
        QUESTION_PLANNER.prompt.version,
    ) == (
        "question_planner",
        "question_plan",
        1,
    )
    assert QUESTION_PLANNER.max_output_tokens == 2048
    schema = QUESTION_PLANNER.response_schema()
    assert sorted(schema["required"]) == ["parts", "step_focus"]
    part: dict[str, object] = {
        "key": "ZR Demand",
        "text": "demand (DCI, 800ZR)",
        "terms": ["800ZR", "ZR", "800ZR"],
        "layer": None,
    }
    other = {**part, "key": "component_supply", "terms": ["ITLA"], "layer": "laser"}
    # The focus written as an object keyed by step: read as the schema's list.
    focus = {"constraint": "Which ZR component is short.", "moat": "not a step"}

    draft = QuestionPlanDraft.model_validate({"parts": [part, other], "step_focus": focus})

    assert [p.key for p in draft.parts] == ["zr_demand", "component_supply"]
    assert draft.parts[0].terms == ["800ZR", "ZR"]
    plan = planned(draft, {"constraint", "relief"})
    assert plan.source == "planner"
    assert plan.step_focus == {"constraint": "Which ZR component is short."}
    # One part, or two with the same key, are refused (repaired once, then quarantined).
    with pytest.raises(ValidationError, match="2 to 6 parts"):
        QuestionPlanDraft.model_validate({"parts": [part], "step_focus": []})
    with pytest.raises(ValidationError, match="unique"):
        QuestionPlanDraft.model_validate({"parts": [part, part], "step_focus": []})
