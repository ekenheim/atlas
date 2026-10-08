"""The Reader's action contract and quote placement (bottleneck-argument ticket 03).

Seams: the role's response model (what the caller validates every answer with) and
`place_quote`, the rule a recorded Fact's quote is placed by. The loop itself is tested
through the `read_step` job (tests/integration/test_reader.py).
"""

import json
from typing import Any, get_args

import pytest
from pydantic import ValidationError

from atlas.facts import FactStatus, FactStep
from atlas.investigations.reader import QuoteRefused, place_quote
from atlas.roles.reader import (
    ARGUMENT_SKEPTIC,
    ARGUMENT_STEPS,
    MAX_FACTS_PER_CALL,
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
    assert (READER.name, READER.prompt.name, READER.prompt.version) == ("reader", "reader", 3)
    # The argument Skeptic names in `challenges` only the Facts its quote denies, limits or
    # dates (skeptic-argument.v3; pilot-review T3).
    assert (
        ARGUMENT_SKEPTIC.name,
        ARGUMENT_SKEPTIC.prompt.name,
        ARGUMENT_SKEPTIC.prompt.version,
    ) == (
        "skeptic",
        "skeptic-argument",
        3,
    )
    schema = READER.response_schema()
    assert schema["additionalProperties"] is False
    assert sorted(schema["required"]) == sorted(["action", *NONE])


def test_control_and_capture_look_for_qualified_sources_and_customer_concentration() -> None:
    steps = {step.key: step for step in ARGUMENT_STEPS}

    assert (
        "how many suppliers the customers have qualified and which competitors the company"
        " itself names" in steps["control"].looks_for
    )
    assert (
        "customer concentration: customers over 10% of revenue and their share (the annual"
        " report's customers paragraph, 'accounted for')" in steps["capture"].looks_for
    )


def test_invalidation_looks_for_what_would_break_the_argument() -> None:
    # Pilot-review R2-03: the invalidation Reader's `looks_for` listed capacity coming online
    # and others' qualification, which Relief and Control record too; 96 of its 211 Facts
    # argued for the thesis.
    invalidation = {step.key: step for step in ARGUMENT_STEPS}["invalidation"]

    assert invalidation.asks == (
        "What would break the argument: evidence that supply has caught up or will, that"
        " demand is slowing, or that another supplier or a substitute takes the scarce"
        " capability."
    )
    looks_for = invalidation.looks_for
    assert looks_for.startswith("Only what would weaken or break the argument:")
    assert "supply caught up" in looks_for
    assert "orders cancelled or pushed out" in looks_for
    assert "Capacity the constrained company itself adds is relief: record it under `relief`" in (
        looks_for
    )
    assert (
        "A statement that repeats the constraint, a record quarter or a plan to expand is never"
        " an invalidation Fact." in looks_for
    )
    assert looks_for.endswith("say in your summary what you searched for and did not find.")


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


def test_an_action_written_flat_or_with_optional_arguments_left_out_is_read_as_meant() -> None:
    from atlas.roles.reader import ReaderAction

    # The arguments beside `action` instead of in its field (the form MiniMax writes).
    flat = ReaderAction.model_validate_json(
        '{"action": "search_archive", "query": "allocation sold out", "company_slugs": ["acme"]}'
    )
    assert flat.search_archive is not None
    assert (flat.search_archive.query, flat.search_archive.company_slugs) == (
        "allocation sold out",
        ["acme"],
    )
    assert flat.read is None and flat.record_fact is None
    # Flat, with the other actions' fields written null.
    read = ReaderAction.model_validate_json(
        '{"action": "read", "ref": "h5", "search_archive": null, "recall": null,'
        ' "record_fact": null, "done": null}'
    )
    assert read.read is not None and read.read.ref == "h5" and read.read.window is None
    # Nested, with the optional arguments left out.
    fact = ReaderAction.model_validate_json(
        '{"action": "record_fact", "record_fact": {"passage_id": "p4", "quote": "We are sold'
        ' out.", "company_slug": "acme", "step": "demand_vs_supply", "statement": "Acme says it'
        ' is sold out.", "status": "in_effect"}}'
    )
    assert fact.record_fact is not None
    [one] = fact.record_fact.facts  # one Fact's arguments alone: the reader.v1 form
    assert (one.quantity, one.period, one.challenges) == (None, None, [])
    # A required argument still missing is still an error.
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ReaderAction.model_validate_json('{"action": "search_archive", "company_slugs": []}')


def test_an_action_inside_action_or_split_between_levels_is_read_as_meant() -> None:
    from atlas.roles.reader import ReaderAction

    inside = ReaderAction.model_validate_json(
        '{"action": {"search_archive": {"query": "InP capacity", "company_slugs": []},'
        ' "recall": null, "read": null, "record_fact": null, "done": null}}'
    )
    assert inside.action == "search_archive"
    assert inside.search_archive is not None and inside.search_archive.query == "InP capacity"
    split = ReaderAction.model_validate_json(
        '{"action": "search_archive", "query": "EML capacity",'
        ' "search_archive": {"company_slugs": ["acme"]}, "recall": null, "read": null,'
        ' "record_fact": null, "done": null}'
    )
    assert split.search_archive is not None
    assert (split.search_archive.query, split.search_archive.company_slugs) == (
        "EML capacity",
        ["acme"],
    )


# One synthetic Fact's arguments, as the model writes them.
FACT: dict[str, Any] = {
    "passage_id": "p2",
    "quote": "Our six-inch line ran at 4,000 wafer starts per month.",
    "company_slug": "acme",
    "step": "constraint",
    "statement": "Acme's six-inch line ran at 4,000 wafer starts per month.",
    "quantity": {"value": 4000, "unit": "wafer starts per month", "metric": "line capacity"},
    "period": None,
    "status": "in_effect",
    "challenges": [],
}


@pytest.mark.parametrize("key", ["args", "arguments", "action_args", "read_args", "params"])
def test_arguments_under_another_key_are_taken_as_the_action_s(key: str) -> None:
    read = ReaderAction.model_validate_json(
        json.dumps(
            {
                "action": "read",
                key: {"ref": "p3", "source_version_id": None, "anchor": None, "window": 3},
                "search_archive": None,
                "recall": None,
                "record_fact": None,
                "done": None,
            }
        )
    )

    assert read.read is not None and (read.read.ref, read.read.window) == ("p3", 3)
    # With the action's field left out altogether, and for a search.
    searched = ReaderAction.model_validate_json(
        json.dumps({"action": "search_archive", key: {"query": "lead times"}})
    )
    assert searched.search_archive is not None
    assert (searched.search_archive.query, searched.search_archive.company_slugs) == (
        "lead times",
        [],
    )


def test_a_wrapper_holding_the_action_s_field_is_unwrapped_and_one_fact_is_a_list_of_one() -> None:
    # {"args": {"record_fact": {...}}}: the form of a repair on 0.5.1's run; `challenges` null.
    answer = ReaderAction.model_validate_json(
        json.dumps({"action": "record_fact", "args": {"record_fact": {**FACT, "challenges": None}}})
    )

    assert answer.record_fact is not None
    [one] = answer.record_fact.facts
    assert (one.passage_id, one.challenges) == ("p2", [])
    assert one.quantity is not None and one.quantity.value == 4000


def test_a_fact_s_quantity_written_flat_is_not_taken_for_a_wrapper() -> None:
    answer = ReaderAction.model_validate_json(json.dumps({"action": "record_fact", **FACT}))

    assert answer.record_fact is not None
    [one] = answer.record_fact.facts
    assert one.quantity is not None and one.quantity.unit == "wafer starts per month"


def test_two_unknown_objects_are_not_guessed_between() -> None:
    with pytest.raises(ValidationError):
        ReaderAction.model_validate_json(
            json.dumps(
                {
                    "action": "search_archive",
                    "args": {"query": "allocation"},
                    "options": {"query": "lead times"},
                }
            )
        )


def test_record_fact_carries_several_facts() -> None:
    second = {**FACT, "quote": "We expect 6,000 by the end of 2027.", "status": "planned"}
    second.pop("challenges")  # optional arguments left out, per Fact
    answer = ReaderAction.model_validate(action("record_fact", facts=[FACT, second]))

    assert answer.record_fact is not None
    assert [f.status for f in answer.record_fact.facts] == ["in_effect", "planned"]
    assert answer.record_fact.facts[1].challenges == []
    # The list written as the action's field itself, or beside `action`.
    listed = ReaderAction.model_validate_json(
        json.dumps({"action": "record_fact", "record_fact": [FACT, second]})
    )
    assert listed.record_fact is not None and len(listed.record_fact.facts) == 2
    flat = ReaderAction.model_validate_json(
        json.dumps({"action": "record_fact", "facts": [FACT, second]})
    )
    assert flat.record_fact is not None and len(flat.record_fact.facts) == 2


@pytest.mark.parametrize("count", [0, MAX_FACTS_PER_CALL + 1])
def test_record_fact_carries_one_to_eight_facts(count: int) -> None:
    assert MAX_FACTS_PER_CALL == 8
    with pytest.raises(ValidationError, match="1 to 8 facts"):
        ReaderAction.model_validate(action("record_fact", facts=[FACT] * count))


def test_the_schema_asks_for_a_list_of_facts() -> None:
    schema = READER.response_schema()
    facts = schema["$defs"]["RecordFacts"]
    assert facts["required"] == ["facts"]
    assert facts["properties"]["facts"]["type"] == "array"


def test_a_quantity_the_model_writes_as_text_or_incomplete_does_not_cost_the_facts() -> None:
    from atlas.roles.reader import ReaderAction

    def fact(quantity: str) -> str:
        return (
            '{"passage_id": "p1", "quote": "Our share is 70%-80% and book-to-bill was 1.6.",'
            ' "company_slug": "acme", "step": "demand_vs_supply", "statement": "Acme says so.",'
            f' "quantity": {quantity}, "period": null, "status": "in_effect", "challenges": []}}'
        )

    answer = ReaderAction.model_validate_json(
        '{"action": "record_fact", "record_fact": {"facts": ['
        + ", ".join(
            [
                fact('"70%-80%"'),  # text: no quantity
                fact('{"value": "1.6", "unit": "ratio"}'),  # a numeric string, no metric
                fact('{"value": "70-80", "unit": "%", "metric": "share"}'),  # a range: none
                fact('{"value": 1.6, "unit": "ratio", "metric": "book-to-bill", "as_of": "Q3"}'),
            ]
        )
        + "]}}"
    )
    assert answer.record_fact is not None
    quantities = [f.quantity for f in answer.record_fact.facts]
    assert quantities[0] is None and quantities[2] is None
    assert quantities[1] is not None
    assert (quantities[1].value, quantities[1].unit, quantities[1].metric) == (1.6, "ratio", "")
    assert quantities[3] is not None and quantities[3].metric == "book-to-bill"
