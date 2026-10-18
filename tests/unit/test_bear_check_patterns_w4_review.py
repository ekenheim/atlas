"""The review of the mechanical bear checks' patterns (Chokepoint Watch ticket W4): a check may
say `clear` only on positive evidence, a customer's share is its current period's, and the
patterns separate a customer from a region, a table row from prose, and one customer from a
group. Hand-written sentences in, the matching sentence and its span out."""

from decimal import Decimal

import pytest

from atlas.bear_checks.patterns import (
    customer_concentration,
    going_concern,
    no_large_customer,
)

FILLER = "The company designs and sells optical components to customers in several markets."


# --- going concern: only a denial is a denial --------------------------------------------------


@pytest.mark.parametrize(
    "sentence",
    [
        "Without additional financing, there is substantial doubt about our ability to continue"
        " as a going concern.",
        "The new facilities have not alleviated the substantial doubt about our ability to"
        " continue as a going concern.",
        "Our losses have not eliminated substantial doubt about our ability to continue as a"
        " going concern.",
        "A failure to raise capital could raise substantial doubt about our ability to continue"
        " as a going concern if the notes are not refinanced.",
        "There is substantial doubt about the ability of the Company to continue as a going"
        " concern.",
        "These conditions raise substantial doubt about its ability to continue as a going"
        " concern.",
    ],
)
def test_a_sentence_that_states_or_imagines_the_doubt_is_never_negated(sentence: str):
    (match,) = going_concern(f"{FILLER} {sentence}")

    assert not match.negated


@pytest.mark.parametrize(
    "sentence",
    [
        "Management concluded that there is no substantial doubt about our ability to continue"
        " as a going concern.",
        "Substantial doubt about our ability to continue as a going concern has been alleviated.",
        "The substantial doubt about the ability of the Company to continue as a going concern"
        " was alleviated by the offering.",
        "Substantial doubt about our ability to continue as a going concern no longer exists.",
        "These results did not raise substantial doubt about our ability to continue as a going"
        " concern.",
        "Our financing alleviated substantial doubt about our ability to continue as a going"
        " concern.",
    ],
)
def test_only_an_actual_denial_is_negated(sentence: str):
    (match,) = going_concern(f"{FILLER} {sentence}")

    assert match.negated


# --- customer concentration -------------------------------------------------------------------


def one(text: str):
    (match,) = customer_concentration(text)
    return match


def test_the_current_period_is_the_first_percentage_not_the_largest():
    match = one(
        "Customer A accounted for 12%, 30% and 22% of our revenue in fiscal 2026, 2025 and 2024."
    )

    assert match.percents == (Decimal("12"), Decimal("30"), Decimal("22"))
    assert match.current == Decimal("12")


def test_a_list_in_ascending_years_takes_the_last_percentage_as_current():
    match = one("Customer A accounted for 12%, 30% and 22% of our revenue in 2024, 2025 and 2026.")

    assert match.current == Decimal("22")


def test_a_table_takes_the_first_column_unless_its_header_runs_oldest_first():
    newest_first = (
        "Net revenue from a single end customer is summarized below:\n"
        "June 27, 2026\tJune 28, 2025\tJune 29, 2024\n"
        "Customer A\t26.6\t%\t15.4\t%\t18.9\t%\n"
    )
    oldest_first = (
        "Net revenue from a single end customer is summarized below:\n"
        "2024\t2025\t2026\n"
        "Customer A\t18.9\t%\t15.4\t%\t26.6\t%\n"
    )

    assert one(newest_first).current == Decimal("26.6")
    assert one(oldest_first).current == Decimal("26.6")  # the 2026 column


def test_more_than_and_or_more_are_lower_bounds_not_values():
    floors = [
        one("Two customers each contributed more than 10% of our revenue."),
        one("One customer represented 10% or more of our net revenue."),
        one("A customer accounted for over 15% of total revenue."),
    ]
    exact = one("Customer A accounted for approximately 12% of our revenue.")

    assert [each.floor for each in floors] == [True, True, True]
    assert exact.floor is False


def test_percent_is_spelled_out_too():
    match = one("Customer A accounted for 32 percent of our net revenue.")

    assert match.current == Decimal("32")


@pytest.mark.parametrize(
    "sentence",
    [
        "Customers in China accounted for 40% of our revenue.",
        "Customers in Asia accounted for 61% of our revenue.",
        "Customers located in Europe represented 35% of net sales.",
        "Net revenue from customers outside the United States represented 79.2% of net revenue.",
        "Approximately 45% of our revenue was derived from customers in Taiwan and Japan.",
        "Customers in the Americas comprised 28% of our total revenue.",
    ],
)
def test_a_region_or_country_is_not_a_customer(sentence: str):
    assert customer_concentration(f"{FILLER} {sentence}") == []


@pytest.mark.parametrize(
    "sentence",
    [
        "Customer A, located in China, accounted for 31% of our revenue.",
        "Apple, our largest customer, which is headquartered in the U.S., accounted for 30%"
        " of our net revenue.",
        "Sales to Foxconn in Asia represented 27% of our revenue.",
    ],
)
def test_a_named_customer_is_kept_even_when_a_place_is_mentioned(sentence: str):
    assert len(customer_concentration(f"{FILLER} {sentence}")) == 1


def test_prose_that_looks_like_a_row_is_not_a_table_row():
    # No tab: not a table cell line.
    assert (
        customer_concentration(f"{FILLER}\nSales and revenue by customer.\nCustomer A 40 %\n") == []
    )


def test_a_receivables_row_is_not_revenue_concentration():
    text = (
        f"{FILLER}\nAccounts receivable by customer:\nCustomer A\t41\t%\t30\t%\n"
        "Net revenue by customer:\n"
    )

    assert customer_concentration(text) == []


@pytest.mark.parametrize(
    "sentence",
    [
        "Our ten largest customers accounted for 62% of our net revenue.",
        "Our top five customers represented 55% of total revenue.",
        "The three largest customers comprised 48% of net sales.",
        "Our top 10 customers accounted for approximately 70% of revenue.",
    ],
)
def test_a_group_of_customers_is_reported_apart_from_a_single_customer(sentence: str):
    match = one(f"{FILLER} {sentence}")

    assert match.kind == "top_customers"
    assert match.percents[0] >= 48


def test_a_single_customer_sentence_is_kind_customer():
    assert one("Customer A accounted for 31% of our revenue.").kind == "customer"


# --- the statement that no customer is large --------------------------------------------------


@pytest.mark.parametrize(
    ("sentence", "threshold"),
    [
        ("No single customer accounted for more than 10% of our revenue.", Decimal("10")),
        ("No customer represented 10% or more of our net revenue in fiscal 2026.", Decimal("10")),
        ("None of our customers accounted for more than 15% of total revenue.", Decimal("15")),
        ("No individual customer exceeded 10% of net sales.", Decimal("10")),
    ],
)
def test_the_statement_that_no_customer_exceeded_a_threshold_is_found(
    sentence: str, threshold: Decimal
):
    text = f"{FILLER} {sentence} More text."

    (match,) = no_large_customer(text)

    assert match.threshold == threshold
    assert text[match.char_start : match.char_end] == sentence
    # It is evidence of no concentration, not a customer's share.
    assert customer_concentration(text) == []


def test_other_sentences_are_not_that_statement():
    assert no_large_customer(f"{FILLER} Two customers each contributed more than 10%.") == []
