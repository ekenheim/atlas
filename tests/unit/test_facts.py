"""The Fact's quantity rule and value validation (no database)."""

import pytest
from pydantic import ValidationError

from atlas.assertions import InvalidAssertion
from atlas.facts import FactValue, Quantity
from atlas.facts.service import check_quantity, check_status


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


def test_a_fact_value_carries_an_optional_part() -> None:
    # Pilot-review R2-01: the key of the question's part a Reader's Fact answers, kept in the
    # Assertion's value_json; none for background, and none on Facts recorded before it.
    good = {"step": "relief", "statement": "A second source qualified.", "status": "planned"}
    assert FactValue.model_validate(good).part is None
    tagged = FactValue.model_validate(good | {"part": "zr_demand"})
    assert tagged.part == "zr_demand"
    assert tagged.model_dump(mode="json", exclude_none=True)["part"] == "zr_demand"
    assert "part" not in FactValue.model_validate(good).model_dump(mode="json", exclude_none=True)


AGREEMENT = (
    "On June 26, 2026, we entered into a Master Development and Supply Agreement with Halden"
    " Optics for the development and supply of 6-inch substrates for an initial term of three"
    " years."
)
AGREEMENT_STATEMENT = (
    "Vantor Photonics entered into a Master Development and Supply Agreement with Halden Optics"
    " for 6-inch substrates."
)


def test_an_agreement_recorded_as_in_development_is_refused_naming_the_status_to_use() -> None:
    with pytest.raises(InvalidAssertion) as refused:
        check_status(AGREEMENT, AGREEMENT_STATEMENT, "in_development")

    assert refused.value.code == "status_agreement"
    assert "`planned`" in refused.value.message
    # The status the agreement gives passes.
    check_status(AGREEMENT, AGREEMENT_STATEMENT, "planned")
    # Development under way, under an agreement, is in development.
    under_way = "Qualification of the product under the agreement is under way."
    check_status(under_way, "Qualification under the agreement is under way.", "in_development")


@pytest.mark.parametrize(
    "quote",
    [
        "Halden Optics has agreed to reserve a minimum annual commitment of substrates for us.",
        "Corvid Systems has agreed to pay an initial deposit of $40 million.",
        "We signed a letter of intent with Corvid Systems.",
    ],
)
def test_a_reservation_a_deposit_or_a_letter_of_intent_is_not_development(quote: str) -> None:
    with pytest.raises(InvalidAssertion) as refused:
        check_status(quote, "Corvid Systems committed to buy.", "in_development")

    assert refused.value.code == "status_agreement"


def test_development_without_an_agreement_is_in_development() -> None:
    check_status(
        "We are sampling 1.6T transceivers with two customers.",
        "Vantor Photonics is sampling 1.6T transceivers.",
        "in_development",
    )


def test_a_company_s_own_estimate_recorded_as_a_third_party_report_is_refused() -> None:
    own = "We're looking at about 40% between us and our competitor."
    statement = "Vantor Photonics estimates it and its competitor hold about 40% each."

    with pytest.raises(InvalidAssertion) as refused:
        check_status(own, statement, "reported_by_third_party")

    assert refused.value.code == "status_first_person"
    assert "in_effect" in refused.value.message
    # Its own estimate, stated as its view of the market, is in effect.
    check_status(own, statement, "in_effect")
    # Another party as the source, even in the company's words.
    check_status(
        "According to industry sources, we expect demand to double.",
        "Industry sources expect demand to double.",
        "reported_by_third_party",
    )


def test_a_third_party_report_without_first_person_passes() -> None:
    check_status(
        "Sumitomo is doubling its substrate capacity.",
        "Sumitomo is doubling its substrate capacity.",
        "reported_by_third_party",
    )
    # "US" is the country, not a pronoun.
    check_status(
        "Demand in the US exceeds supply, Corvid Systems said.",
        "Corvid Systems said US demand exceeds supply.",
        "reported_by_third_party",
    )
