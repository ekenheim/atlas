"""The counter-judge's contract (pilot-review T3): what the caller validates its answers with.

Seam: the role's response model and strict schema.
"""

from typing import Any

import pytest
from pydantic import ValidationError

from atlas.roles.counter_judge import (
    CONTRADICTING,
    COUNTER_JUDGE,
    COUNTER_JUDGE_VERSION,
    CounterJudgement,
)

RELATIONS = ["contradicts", "limits", "dates", "qualifies", "supports", "unrelated"]


def test_the_role_is_counter_judge_v1() -> None:
    assert (COUNTER_JUDGE.name, COUNTER_JUDGE.prompt.name, COUNTER_JUDGE.prompt.version) == (
        "counter_judge",
        "counter_judge",
        1,
    )
    assert COUNTER_JUDGE_VERSION == "counter_judge.v1"
    assert COUNTER_JUDGE.max_output_tokens == 2048


def test_its_strict_schema_requires_relations() -> None:
    schema = COUNTER_JUDGE.response_schema()
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["relations"]
    relation: dict[str, Any] = schema["$defs"]["CounterRelation"]
    assert relation["additionalProperties"] is False
    assert sorted(relation["required"]) == ["reason", "ref", "relation"]
    assert sorted(relation["properties"]["relation"]["enum"]) == sorted(RELATIONS)


@pytest.mark.parametrize("relation", RELATIONS)
def test_relation_accepts_each_of_the_six(relation: str) -> None:
    answer = CounterJudgement.model_validate(
        {"relations": [{"ref": "f1", "relation": relation, "reason": "k1 says so"}]}
    )
    assert answer.relations[0].relation == relation


@pytest.mark.parametrize("relation", ["contradict", "denies", "unjudged", "CONTRADICTS", ""])
def test_relation_refuses_anything_else(relation: str) -> None:
    with pytest.raises(ValidationError):
        CounterJudgement.model_validate(
            {"relations": [{"ref": "f1", "relation": relation, "reason": "k1 says so"}]}
        )


def test_only_contradicts_limits_and_dates_speak_against_a_fact() -> None:
    assert frozenset({"contradicts", "limits", "dates"}) == CONTRADICTING
