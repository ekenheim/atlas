"""The argument's Editor answers with several statements per step (`editor-argument.v2`); an
answer in the v1 shape (one statement per step) is read as a list of that one statement."""

from typing import Any

import pytest
from pydantic import ValidationError

from atlas.roles.editor import EDITOR_ARGUMENT, ArgumentCardDraft, ArgumentFactItem


def card(*steps: dict[str, Any]) -> dict[str, Any]:
    return {"steps": list(steps), "open_questions": [], "verdict": "needs_review"}


def test_a_step_has_several_statements_each_citing_its_own_facts() -> None:
    draft = ArgumentCardDraft.model_validate(
        card(
            {
                "step": "constraint",
                "status": "supported",
                "statements": [
                    {"statement": "A runs 4,000 wafers.", "fact_refs": ["c1"], "counter_refs": []},
                    {
                        "statement": "A expects 6,000 by 2027.",
                        "fact_refs": ["c1", "c2"],
                        "counter_refs": ["c9"],
                    },
                ],
                "unchecked": ["demand"],
            }
        )
    )

    [step] = draft.steps
    assert [(s.statement, s.fact_refs, s.counter_refs) for s in step.statements] == [
        ("A runs 4,000 wafers.", ["c1"], []),
        ("A expects 6,000 by 2027.", ["c1", "c2"], ["c9"]),
    ]


def test_the_v1_shape_is_read_as_a_list_of_one_statement() -> None:
    draft = ArgumentCardDraft.model_validate(
        card(
            {
                "step": "relief",
                "status": "disputed",
                "statement": "A plans a second fab.",
                "fact_refs": ["c3"],
                "counter_refs": ["c4"],
                "unchecked": [],
            },
            {
                "step": "capture",
                "status": "unknown",
                "statement": "The Facts do not establish this step.",
                "fact_refs": None,
                "unchecked": [],
            },
        )
    )

    relief, capture = draft.steps
    assert (relief.status, relief.unchecked) == ("disputed", [])
    assert [(s.statement, s.fact_refs, s.counter_refs) for s in relief.statements] == [
        ("A plans a second fab.", ["c3"], ["c4"])
    ]
    assert [(s.statement, s.fact_refs, s.counter_refs) for s in capture.statements] == [
        ("The Facts do not establish this step.", [], [])
    ]


def test_a_step_with_neither_shape_fails_validation() -> None:
    with pytest.raises(ValidationError):
        ArgumentCardDraft.model_validate(
            card({"step": "relief", "status": "unknown", "unchecked": []})
        )
    with pytest.raises(ValidationError):  # extra keys beside the list are still refused
        ArgumentCardDraft.model_validate(
            card(
                {
                    "step": "relief",
                    "status": "unknown",
                    "statements": [],
                    "fact_refs": [],
                    "unchecked": [],
                }
            )
        )


def test_the_strict_schema_asks_for_the_list_of_statements() -> None:
    schema = EDITOR_ARGUMENT.response_schema()

    step = schema["$defs"]["ArgumentStepDraft"]
    assert step["required"] == ["step", "status", "statements", "unchecked"]
    assert step["additionalProperties"] is False
    statement = schema["$defs"]["ArgumentStatementDraft"]
    assert statement["required"] == ["statement", "fact_refs", "counter_refs"]
    assert statement["additionalProperties"] is False
    assert (EDITOR_ARGUMENT.prompt.name, EDITOR_ARGUMENT.prompt.version) == ("editor-argument", 2)


def test_the_editor_is_sent_each_fact_s_source_date() -> None:
    schema = EDITOR_ARGUMENT.request.model_json_schema()
    fact = schema["$defs"]["ArgumentFactItem"]
    assert "source_date" in fact["required"]
    item = ArgumentFactItem(
        ref="c1",
        step="constraint",
        company="Zephyr Optics",
        statement="Zephyr is sold out.",
        status="in_effect",
        quantity=None,
        period=None,
        source_title="Q3 2026",
        source_date="2025-11-05",
        against=[],
    )
    assert item.model_dump(mode="json")["source_date"] == "2025-11-05"
