"""The deterministic half of Relationship review (spec "Relationships", "Review"): the
directional-language checker, the verbatim-span and Tier A checks, and how they combine
with the Reviewer's classification into `machine_reviewed` or `needs_human_review`."""

import pytest

from atlas.relationships import (
    DeterministicChecks,
    ReviewerAnswer,
    deterministic_checks,
    directional_language,
    review_outcome,
)
from atlas.roles.reviewer import REVIEWER

# From the Coherent FY2026 10-K (the recorded fixture's parsed text).
SUPPLY_QUOTE = (
    "we announced the expansion of our Sherman, Texas, manufacturing facility, entered into a"
    " strategic multi-year supply agreement with NVIDIA for advanced lasers and optical"
    " networking products"
)
PEER_GROUP_QUOTE = (
    "The Company\N{RIGHT SINGLE QUOTATION MARK}s peer group includes IPG Photonics Corp.,"
    " Wolfspeed Inc., Lumentum Holdings, Inc., Corning, Inc., MKS Instruments, Inc., and"
    " Honeywell International, Inc."
)
CONFIRMED = ReviewerAnswer(verdict="confirmed", direction="as_proposed", layer="correct")


# --- the directional-language checker ------------------------------------------------------------


def test_a_directional_quote_is_explicit_and_names_its_cue() -> None:
    found = directional_language("supplies", SUPPLY_QUOTE)

    assert (found.verdict, found.cue, found.hedge) == ("explicit", "supply", None)


def test_co_mention_has_no_directional_language() -> None:
    for predicate in ["supplies", "buys_from", "competes_with", "depends_on", "owns"]:
        found = directional_language(predicate, PEER_GROUP_QUOTE)
        assert (found.verdict, found.cue) == ("absent", None)


@pytest.mark.parametrize(
    ("quote", "hedge"),
    [
        ("We may enter into a supply agreement with NVIDIA.", "may"),
        ("Coherent expects to supply NVIDIA with lasers next year.", "expects to"),
        ("We are in discussions to supply NVIDIA.", "in discussions"),
        ("NVIDIA could become a customer of ours.", "could"),
        ("We signed a non-binding memorandum of understanding to supply NVIDIA.", "non-binding"),
        ("NVIDIA is reportedly a customer of Coherent.", "reportedly"),
    ],
)
def test_hedged_language_is_not_explicit(quote: str, hedge: str) -> None:
    found = directional_language("supplies", quote)

    assert found.verdict == "hedged"
    assert found.hedge is not None and found.hedge.lower() == hedge
    assert found.cue is not None


def test_the_month_of_may_is_not_a_hedge() -> None:
    found = directional_language("supplies", "In May 2026, we began shipping lasers to NVIDIA.")

    assert (found.verdict, found.cue) == ("explicit", "shipping")


def test_patterns_find_directional_language_but_leave_its_direction_to_the_reviewer() -> None:
    # Who "we" is decides the direction; the Reviewer's classification judges it.
    found = directional_language("supplies", "We purchase lasers from NVIDIA under a supply deal.")

    assert (found.verdict, found.cue) == ("explicit", "supply")


def test_buying_is_explicit_for_buys_from_and_absent_for_supplies() -> None:
    quote = "We purchase indium phosphide substrates from Sumitomo."

    assert directional_language("buys_from", quote).verdict == "explicit"
    assert directional_language("supplies", quote).verdict == "absent"


def test_an_unlisted_predicate_has_no_directional_language() -> None:
    assert directional_language("partners_with", SUPPLY_QUOTE).verdict == "absent"


# --- the deterministic checks ---------------------------------------------------------------------


def parsed_with(quote: str, before: str = "Item 1. Business\n") -> tuple[str, int, int]:
    text = f"{before}{quote} More text follows."
    return text, len(before), len(before) + len(quote)


def test_a_verbatim_tier_a_explicit_quote_passes_every_deterministic_check() -> None:
    parsed, start, end = parsed_with(SUPPLY_QUOTE)

    checks = deterministic_checks(
        predicate="supplies",
        quote=SUPPLY_QUOTE,
        span_start=start,
        span_end=end,
        parsed_text=parsed,
        source_tier="A",
    )

    assert (checks.verbatim_span, checks.tier_a, checks.language.verdict) == (
        True,
        True,
        "explicit",
    )
    assert checks.reasons == []
    assert checks.passed


def test_each_failed_deterministic_check_is_a_reason() -> None:
    parsed, start, end = parsed_with(SUPPLY_QUOTE)

    moved = deterministic_checks(
        predicate="supplies",
        quote=SUPPLY_QUOTE,
        span_start=start + 1,
        span_end=end + 1,
        parsed_text=parsed,
        source_tier="A",
    )
    unreadable = deterministic_checks(
        predicate="supplies",
        quote=SUPPLY_QUOTE,
        span_start=start,
        span_end=end,
        parsed_text=None,
        source_tier="B",
    )
    hedged = deterministic_checks(
        predicate="supplies",
        quote="We may supply NVIDIA.",
        span_start=0,
        span_end=21,
        parsed_text="We may supply NVIDIA.",
        source_tier="C",
    )

    assert moved.reasons == ["span_not_verbatim"]
    assert unreadable.reasons == ["span_not_verbatim", "not_tier_a"]
    assert hedged.reasons == ["not_tier_a", "hedged_language"]
    assert not (moved.passed or unreadable.passed or hedged.passed)


# --- combining with the Reviewer ------------------------------------------------------------------


def passing() -> DeterministicChecks:
    parsed, start, end = parsed_with(SUPPLY_QUOTE)
    return deterministic_checks(
        predicate="supplies",
        quote=SUPPLY_QUOTE,
        span_start=start,
        span_end=end,
        parsed_text=parsed,
        source_tier="A",
    )


def test_all_checks_passing_and_a_confirmed_direction_and_layer_is_machine_reviewed() -> None:
    assert review_outcome(passing(), CONFIRMED) == ("machine_reviewed", [])


@pytest.mark.parametrize(
    ("answer", "reasons"),
    [
        (ReviewerAnswer("rejected", "as_proposed", "correct"), ["reviewer_rejected"]),
        (ReviewerAnswer("uncertain", "as_proposed", "correct"), ["reviewer_uncertain"]),
        (ReviewerAnswer("confirmed", "reversed", "correct"), ["direction_not_confirmed"]),
        (ReviewerAnswer("confirmed", "undirected", "correct"), ["direction_not_confirmed"]),
        (ReviewerAnswer("confirmed", "as_proposed", "wrong"), ["layer_not_confirmed"]),
        (
            ReviewerAnswer("rejected", "reversed", "unclear"),
            ["reviewer_rejected", "direction_not_confirmed", "layer_not_confirmed"],
        ),
    ],
)
def test_anything_short_of_a_confirmation_goes_to_the_exceptions_queue(
    answer: ReviewerAnswer, reasons: list[str]
) -> None:
    assert review_outcome(passing(), answer) == ("needs_human_review", reasons)


def test_without_a_reviewer_answer_nothing_is_machine_reviewed() -> None:
    assert review_outcome(passing(), None, missing="reviewer_quarantined") == (
        "needs_human_review",
        ["reviewer_quarantined"],
    )


def test_the_reviewer_role_has_a_strict_schema_and_a_versioned_prompt() -> None:
    schema = REVIEWER.response_schema()

    assert REVIEWER.name == "reviewer"
    assert (REVIEWER.prompt.name, REVIEWER.prompt.version) == ("reviewer", 3)
    assert schema["additionalProperties"] is False
    review = schema["$defs"]["EdgeReview"]
    assert sorted(review["required"]) == sorted(review["properties"])


def test_the_reviewer_prompt_names_both_precision_failure_shapes_with_the_pilot_s_sentences() -> (
    None
):
    # pilot-fixes ticket 09: generic risk-factor language and a cue from another clause.
    text = " ".join(REVIEWER.prompt.text.split())
    for phrase in [
        "Generic risk-factor language for a bottleneck predicate",
        "some of our suppliers are our sole sources for certain materials, equipment and"
        " components",
        "we purchase raw materials, packages and components from a limited number of suppliers",
        "exotic materials, crystals, and optics",
        "never the layer the research question is about",
        "A cue that belongs to another clause",
        "while also operating multiple 6-inch GaAs VCSEL manufacturing facilities",
    ]:
        assert phrase in text, phrase
