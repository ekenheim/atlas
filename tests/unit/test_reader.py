"""The Reader's action contract and quote placement (bottleneck-argument ticket 03).

Seams: the role's response model (what the caller validates every answer with) and
`place_quote`, the rule a recorded Fact's quote is placed by. The loop itself is tested
through the `read_step` job (tests/integration/test_reader.py).
"""

from typing import Any, get_args

import pytest
from pydantic import ValidationError

from atlas.facts import FactStatus, FactStep
from atlas.investigations.reader import QuoteRefused, place_quote
from atlas.roles.reader import (
    ARGUMENT_STEPS,
    READER,
    ArgumentStep,
    FactStatusName,
    FactStepName,
    ReaderAction,
)

NONE: dict[str, Any] = {
    "search_archive": None,
    "recall": None,
    "read": None,
    "record_fact": None,
    "done": None,
}


def action(name: str, **args: Any) -> dict[str, Any]:
    return {"action": name, **NONE, name: args}


def test_an_action_carries_its_arguments_in_the_field_of_its_name() -> None:
    searched = ReaderAction.model_validate(
        action("search_archive", query="wafer starts per month", company_slugs=["coherent"])
    )

    assert searched.search_archive is not None
    assert searched.search_archive.company_slugs == ["coherent"]
    done = ReaderAction.model_validate(action("done", summary="nothing more to find"))
    assert done.done is not None and done.done.summary == "nothing more to find"


def test_an_action_naming_one_action_and_filling_another_is_invalid() -> None:
    answer = action("read", ref="h1", source_version_id=None, anchor=None, window=None)
    answer["action"] = "search_archive"

    with pytest.raises(ValidationError, match="needs its arguments in the field"):
        ReaderAction.model_validate(answer)


def test_two_actions_at_once_are_invalid() -> None:
    answer = action("done", summary="done")
    answer["recall"] = {"query": "lead times"}

    with pytest.raises(ValidationError, match="every other action field null"):
        ReaderAction.model_validate(answer)


def test_a_fact_s_step_and_status_are_the_fact_model_s() -> None:
    assert get_args(FactStepName) == get_args(FactStep)
    assert get_args(FactStatusName) == get_args(FactStatus)
    assert [step.key for step in ARGUMENT_STEPS] == list(get_args(ArgumentStep))
    assert set(get_args(ArgumentStep)) == set(get_args(FactStep)) - {"context"}


def test_the_role_is_versioned_and_its_schema_strict() -> None:
    assert (READER.name, READER.prompt.name, READER.prompt.version) == ("reader", "reader", 1)
    schema = READER.response_schema()
    assert schema["additionalProperties"] is False
    assert sorted(schema["required"]) == sorted(["action", *NONE])


CURLY = "\N{RIGHT SINGLE QUOTATION MARK}"
TEXT = (
    "Cover page.\n"
    "We shipped 1.6T modules in the quarter. Demand for our lasers exceeds supply.\n"
    f"Our partner{CURLY}s fab is sold out through 2027.\n"
    "Demand for our lasers exceeds supply.\n"
)
PASSAGE = (TEXT.index("We shipped"), TEXT.index("Our partner"))


def test_a_quote_is_placed_at_its_one_occurrence_in_the_passage() -> None:
    placed = place_quote(TEXT, *PASSAGE, "We shipped 1.6T modules in the quarter.")

    assert placed == (PASSAGE[0], PASSAGE[0] + len("We shipped 1.6T modules in the quarter."))


def test_a_quote_with_straight_quotes_is_placed_through_the_fold() -> None:
    start = TEXT.index("Our partner")
    placed = place_quote(TEXT, start, len(TEXT), "Our partner's fab is sold out")

    assert placed == (start, start + len("Our partner's fab is sold out"))
    assert TEXT[start : start + len("Our partner's fab is sold out")].startswith(
        f"Our partner{CURLY}s"
    )


def test_a_quote_outside_the_passage_is_placed_by_its_one_occurrence_in_the_document() -> None:
    placed = place_quote(TEXT, *PASSAGE, "fab is sold out through 2027")

    start = TEXT.index("fab is sold out")
    assert placed == (start, start + len("fab is sold out through 2027"))


def test_a_quote_twice_in_the_document_is_ambiguous_unless_the_passage_has_it_once() -> None:
    in_passage = place_quote(TEXT, *PASSAGE, "Demand for our lasers exceeds supply.")
    elsewhere = place_quote(TEXT, PASSAGE[1], len(TEXT) - 1, "Demand for our lasers exceeds supply")
    cover = place_quote(TEXT, 0, len("Cover page."), "Demand for our lasers exceeds supply")

    assert in_passage == (TEXT.index("Demand"), TEXT.index("Demand") + 37)
    assert not isinstance(elsewhere, QuoteRefused)  # the passage holds it once
    assert isinstance(cover, QuoteRefused) and cover.code == "quote_ambiguous"


def test_a_quote_not_in_the_document_is_not_found() -> None:
    refused = place_quote(TEXT, *PASSAGE, "We supply lasers to every hyperscaler.")

    assert isinstance(refused, QuoteRefused) and refused.code == "quote_not_found"
    assert isinstance(place_quote(TEXT, *PASSAGE, "  "), QuoteRefused)
