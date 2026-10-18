"""The sentence patterns of the mechanical bear checks (Chokepoint Watch ticket W4): hand-written
sentences in, the matching sentence and its span out. The span is the sentence itself, so a
match can be quoted from the parse it was found in."""

from decimal import Decimal

import pytest

from atlas.bear_checks.patterns import (
    customer_concentration,
    going_concern,
    sentence_span,
)

FILLER = "The company designs and sells optical components to customers in several markets."


def only_percents(text: str) -> list[tuple[Decimal, ...]]:
    return [each.percents for each in customer_concentration(text)]


@pytest.mark.parametrize(
    ("sentence", "percents"),
    [
        ("One customer accounted for approximately 32% of our net revenue.", (Decimal("32"),)),
        ("Customer A accounted for 12.5% of total revenue in fiscal 2026.", (Decimal("12.5"),)),
        ("Sales to Amazon represented 41% of our revenues.", (Decimal("41"),)),
        ("Two distributors comprised 27% of net sales.", (Decimal("27"),)),
        ("Huawei, a customer, constituted about 18% of the Company's revenue.", (Decimal("18"),)),
        (
            "Apple, our largest customer, contributed more than 25% of consolidated net revenue.",
            (Decimal("25"),),
        ),
        (
            "Customer A accounted for 12%, 15% and 22% of our revenue in 2024, 2025 and 2026.",
            (Decimal("12"), Decimal("15"), Decimal("22")),
        ),
        (
            "Approximately 30% of our revenue was derived from a single customer.",
            (Decimal("30"),),
        ),
        ("CUSTOMER B ACCOUNTED FOR 45% OF OUR REVENUE.", (Decimal("45"),)),
    ],
)
def test_concentration_variants_are_found_with_their_percentages(
    sentence: str, percents: tuple[Decimal, ...]
):
    assert only_percents(f"{FILLER} {sentence} {FILLER}") == [percents]


@pytest.mark.parametrize(
    "sentence",
    [
        "Revenue grew 32% from the prior year.",
        "Our gross margin was 41% of revenue.",  # no "accounted for": a ratio, not a customer share
        "We expect customers to account for most of our revenue.",
        "One customer accounted for a large part of our revenue.",  # no number
        # A region is not a customer, and neither is a product line.
        "During fiscal 2026, net revenue from customers outside the United States represented"
        " 79.2% of net revenue.",
        "Customers located in Asia accounted for 61% of our revenue.",
        "Our datacom products accounted for 40% of our revenue.",
    ],
)
def test_other_sentences_about_revenue_are_not_concentration(sentence: str):
    assert customer_concentration(f"{FILLER} {sentence}") == []


def test_a_concentration_match_is_the_whole_sentence_and_its_span_is_exact():
    first = "See Note 5, Revenue, for the detail."
    sentence = (
        "In fiscal 2026 one customer, Acme Inc. accounted for approximately 33% of our net revenue."
    )
    text = f"{FILLER}\n\n{first} {sentence} The next sentence follows."

    (match,) = customer_concentration(text)

    assert match.sentence == sentence  # "Inc." does not end the sentence
    assert text[match.char_start : match.char_end] == sentence
    assert match.maximum == Decimal("33")


def test_the_percentages_of_one_sentence_are_one_match_and_two_sentences_are_two():
    text = (
        "Customer A accounted for 11% of our revenue. "
        "Customer B accounted for 26% of our revenue and Customer C for 14%."
    )

    matches = customer_concentration(text)

    assert [each.percents for each in matches] == [(Decimal("11"),), (Decimal("26"),)]
    assert matches[1].sentence.startswith("Customer B")


def test_sentence_span_stops_at_line_breaks_and_trims_whitespace():
    text = "Heading line\n  Customer A accounted for 40% of revenue.  \nNext paragraph."
    start = text.index("40%")

    left, right = sentence_span(text, start, start + 3)

    assert text[left:right] == "Customer A accounted for 40% of revenue."


GOING_CONCERN = (
    "These conditions raise substantial doubt about our ability to continue as a going concern."
)


def test_a_going_concern_sentence_is_found_with_its_span():
    text = f"{FILLER} {GOING_CONCERN} We plan to raise capital."

    (match,) = going_concern(text)

    assert match.sentence == GOING_CONCERN
    assert text[match.char_start : match.char_end] == GOING_CONCERN
    assert not match.negated
    assert not match.hedged


@pytest.mark.parametrize(
    "variant",
    [
        "There is substantial doubt about the Company's ability to continue as a going concern.",
        "Our auditors expressed substantial doubt regarding its ability to continue as a"
        " going concern.",
        "Such losses raise Substantial Doubt about Acme Corp.'s ability to continue as a"
        " going concern.",
    ],
)
def test_going_concern_wording_variants(variant: str):
    (match,) = going_concern(f"{FILLER} {variant}")

    assert not match.negated


@pytest.mark.parametrize(
    "negated",
    [
        "Management concluded there is no substantial doubt about our ability to continue as a"
        " going concern.",
        "These results did not raise substantial doubt about our ability to continue as a"
        " going concern.",
        "Our recent financing alleviated substantial doubt about our ability to continue as a"
        " going concern.",
        "Substantial doubt about our ability to continue as a going concern does not exist.",
    ],
)
def test_a_sentence_that_denies_the_doubt_is_marked_negated(negated: str):
    (match,) = going_concern(f"{FILLER} {negated}")

    assert match.negated


def test_a_sentence_that_only_imagines_the_doubt_is_marked_hedged():
    (match,) = going_concern(
        "If we cannot raise funds, our losses could raise substantial doubt about our ability"
        " to continue as a going concern."
    )

    assert match.hedged
    assert not match.negated


def test_a_text_without_the_phrase_has_no_match():
    assert going_concern(f"{FILLER} Substantial doubt is not discussed here.") == []
