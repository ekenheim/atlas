"""The Fact's quantity rule and value validation (no database)."""

import pytest
from pydantic import ValidationError

from atlas.assertions import InvalidAssertion
from atlas.facts import FactValue, Quantity
from atlas.facts.service import check_quantity


def quantity(value: float, unit: str = "USD") -> Quantity:
    return Quantity(value=value, unit=unit, metric="net revenue")


@pytest.mark.parametrize(
    ("quote", "value"),
    [
        ("Net revenue was $1.01 billion", 1.01),
        ("Net revenue was $1.01 billion", 1_010_000_000),
        ("GAAP gross margin of 47.4%", 47.4),
        ("capacity of 600,100 wafers per month", 600100),
        ("expects to double capacity by 2028", 2028),
        ("a loss of 5 percent", -5),
    ],
)
def test_a_number_the_quote_states_is_accepted(quote: str, value: float) -> None:
    check_quantity(quote, quantity(value))


@pytest.mark.parametrize(
    ("quote", "value"),
    [
        ("Net revenue was $1.01 billion", 2.5),
        ("GAAP gross margin of 47.4%", 47.5),
        ("expects to double capacity by 2028", 2029),
    ],
)
def test_a_number_the_quote_does_not_state_is_refused(quote: str, value: float) -> None:
    with pytest.raises(InvalidAssertion) as refused:
        check_quantity(quote, quantity(value))

    assert refused.value.code == "quantity_not_in_quote"


def test_an_unknown_step_or_status_or_a_blank_statement_is_invalid() -> None:
    good = {"step": "relief", "statement": "A second source qualified.", "status": "planned"}
    FactValue.model_validate(good)
    for bad in (
        good | {"step": "moat"},
        good | {"status": "rumoured"},
        good | {"statement": "  "},
        good | {"period": " "},
        good | {"extra": 1},
    ):
        with pytest.raises(ValidationError):
            FactValue.model_validate(bad)
