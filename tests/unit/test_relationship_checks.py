"""The deterministic half of Relationship review (spec "Relationships", "Review"): the
directional-language checker, the verbatim-span and Tier A checks, and how they combine
with the Reviewer's classification into `machine_reviewed` or `needs_human_review`."""

import pytest

from atlas.relationships import (
    DeterministicChecks,
    ReviewerAnswer,
    brings_layer,
    deterministic_checks,
    directional_language,
    review_outcome,
)
from atlas.roles.reviewer import REVIEWER, LayerVerdict

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
CONFIRMED = ReviewerAnswer(direction="as_proposed", hedge="none", layer="correct")


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
    assert review_outcome(passing(), CONFIRMED, layered=True) == ("machine_reviewed", [])


@pytest.mark.parametrize(
    ("answer", "reasons"),
    [
        # Each check is answered, and recorded, on its own (memory-directed reading ticket 08).
        (ReviewerAnswer("reversed", "none", "correct"), ["direction_not_confirmed"]),
        (ReviewerAnswer("undirected", "none", "correct"), ["direction_not_confirmed"]),
        (ReviewerAnswer("not_stated", "none", "correct"), ["direction_not_confirmed"]),
        (ReviewerAnswer("as_proposed", "hedged", "correct"), ["reviewer_hedged"]),
        # An unconfirmed layer is a layer reason, never a direction one.
        (ReviewerAnswer("as_proposed", "none", "wrong"), ["layer_not_confirmed"]),
        (ReviewerAnswer("as_proposed", "none", "unclear"), ["layer_not_confirmed"]),
        (ReviewerAnswer("as_proposed", "none", "not_proposed"), ["layer_not_confirmed"]),
        (
            ReviewerAnswer("reversed", "hedged", "unclear"),
            ["direction_not_confirmed", "reviewer_hedged", "layer_not_confirmed"],
        ),
    ],
)
def test_anything_short_of_a_confirmation_goes_to_the_exceptions_queue(
    answer: ReviewerAnswer, reasons: list[str]
) -> None:
    assert review_outcome(passing(), answer, layered=True) == ("needs_human_review", reasons)


@pytest.mark.parametrize("layer", ["not_proposed", "correct", "wrong", "unclear"])
def test_an_edge_with_no_layer_is_machine_reviewed_on_its_direction_and_hedge_alone(
    layer: LayerVerdict,
) -> None:
    # No layer was proposed, so whatever the Reviewer says of one is not a reason.
    answer = ReviewerAnswer("as_proposed", "none", layer)
    assert review_outcome(passing(), answer, layered=False) == ("machine_reviewed", [])
    reversed_ = ReviewerAnswer("reversed", "hedged", layer)
    assert review_outcome(passing(), reversed_, layered=False) == (
        "needs_human_review",
        ["direction_not_confirmed", "reviewer_hedged"],
    )


@pytest.mark.parametrize(
    ("answer", "layered", "brought"),
    [
        (CONFIRMED, True, True),
        (None, True, True),  # the Reviewer wasn't asked, or gave no answer: nothing against it
        (ReviewerAnswer("as_proposed", "hedged", "correct"), True, True),
        (ReviewerAnswer("as_proposed", "none", "wrong"), True, False),
        (ReviewerAnswer("as_proposed", "none", "unclear"), True, False),
        (ReviewerAnswer("not_stated", "none", "correct"), True, False),
        (CONFIRMED, False, False),
    ],
)
def test_an_assertion_brings_its_layer_to_the_edge_unless_the_reviewer_refutes_it(
    answer: ReviewerAnswer | None, layered: bool, brought: bool
) -> None:
    assert brings_layer(answer, layered=layered) is brought


def test_without_a_reviewer_answer_nothing_is_machine_reviewed() -> None:
    assert review_outcome(passing(), None, layered=True, missing="reviewer_quarantined") == (
        "needs_human_review",
        ["reviewer_quarantined"],
    )


def test_the_reviewer_role_has_a_strict_schema_and_a_versioned_prompt() -> None:
    schema = REVIEWER.response_schema()

    assert REVIEWER.name == "reviewer"
    assert (REVIEWER.prompt.name, REVIEWER.prompt.version) == ("reviewer", 4)
    assert schema["additionalProperties"] is False
    review = schema["$defs"]["EdgeReview"]
    assert sorted(review["required"]) == sorted(review["properties"])
    # One answer per check: no overall verdict that one failed check could drag down.
    assert sorted(review["properties"]) == [
        "direction",
        "hedge",
        "item_id",
        "layer",
        "reasoning",
        "suggested_layer",
    ]


def test_the_reviewer_prompt_asks_each_check_separately_and_keeps_the_pilot_s_sentences() -> None:
    text = " ".join(REVIEWER.prompt.text.split())
    for phrase in [
        # memory-directed reading ticket 08: three checks, each answered on its own.
        "Answer each of the three checks on its own",
        "A wrong, unclear or missing layer never changes `direction` or `hedge`",
        "When the item's `layer` is null, no layer is proposed: answer `not_proposed`",
        "one of that layer's `terms`, listed in `request.layers`, occurs there",
        "A word of the layer somewhere in the quote is not enough",
        "NVIDIA made a $2 billion investment in the Company",
        "indium phosphide capacity",
        # pilot-fixes ticket 09: generic risk-factor language and a cue from another clause.
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
