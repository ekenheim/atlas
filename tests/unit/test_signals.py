"""Archive bottleneck signals (atlas-beliefs ticket 18): the scorer over hand-written sentences,
and the config that drives it.

The scorer is a pure function of a text, a few facts about the document and the repo's config
(`configs/discovery/signals.yaml`). Every sentence here is written for the test, in the wording
managements and analysts use; none is a recorded sentence of a company, and the expected scores
are worked out by hand from the config's weights (family weight times the phrase's factor, plus
the co-occurrence bonus 1.0 and the figure bonus 0.75, then the factors).
"""

from pathlib import Path

import pytest

from atlas.claims.predicates import company_names
from atlas.discovery.signals import (
    SignalHit,
    SignalsConfigError,
    SignalScorer,
    cap_per_document,
    load_signals_config,
    sentence_spans,
)

CONFIG = Path(__file__).resolve().parents[2] / "configs" / "discovery" / "signals.yaml"
NAMES = company_names("Example Photonics", "Example Photonics Inc.")


@pytest.fixture(scope="module")
def scorer() -> SignalScorer:
    return SignalScorer(load_signals_config(CONFIG))


def scan(
    scorer: SignalScorer,
    text: str,
    *,
    form_type: str | None = None,
    primary: bool = False,
    source_type: str | None = None,
) -> list[SignalHit]:
    return scorer.scan(
        text, form_type=form_type, primary=primary, source_type=source_type, company_names=NAMES
    )


def scored(hits: list[SignalHit]) -> list[tuple[str, float]]:
    return [(hit.quote, hit.score) for hit in hits]


# --- the families -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("sentence", "family", "score"),
    [
        ("Only two companies make this wafer at volume.", "few_suppliers", 2.0),
        ("We cannot keep up with orders from hyperscale customers.", "demand_beyond_supply", 2.0),
        ("Extended lead times of 52 weeks are now common.", "lead_times_backlog", 2.25),
        ("The fab is running at full capacity.", "capacity", 1.5),
        ("Shipments need an export permit that has not yet been issued.", "gates", 1.5),
        ("We raised prices twice this year and the increases have held.", "pricing_power", 1.5),
    ],
)
def test_each_family_is_found_by_wording_written_for_it(
    scorer: SignalScorer, sentence: str, family: str, score: float
) -> None:
    hits = scan(scorer, sentence)

    assert [(hit.quote, hit.families, hit.score) for hit in hits] == [(sentence, (family,), score)]


def test_a_sentence_telling_scarcity_and_its_cause_scores_both_families_and_the_bonus(
    scorer: SignalScorer,
) -> None:
    sentence = (
        "Demand for our wafers is growing too fast, we cannot keep up, and only three suppliers"
        " make it."
    )

    [hit] = scan(scorer, sentence)

    # demand_beyond_supply: 2.0 x (1.0 + 0.25 for a second phrase) = 2.5; few_suppliers: 2.0;
    # two families in the paragraph: + 1.0.
    assert (hit.families, hit.score) == (("few_suppliers", "demand_beyond_supply"), 5.5)
    assert dict(hit.factors) == {"families": 4.5, "cooccurrence": 1.0}
    assert (hit.speaker, hit.speaker_kind) == (None, None)


def test_a_figure_adds_its_bonus(scorer: SignalScorer) -> None:
    sentence = "We ended the quarter with a backlog of more than $10 million."

    assert scored(scan(scorer, sentence)) == [(sentence, 2.25)]  # 1.5 + 0.75


def test_being_adequately_served_is_a_signal_only_when_it_is_denied(scorer: SignalScorer) -> None:
    sentence = "The market cannot be adequately served by the two players that make it."

    assert scored(scan(scorer, sentence)) == [(sentence, 4.2)]  # 2.0 + 1.2 (two players) + 1.0
    assert scan(scorer, "The market is adequately served by the players that make it.") == []


def test_a_bare_word_of_a_family_is_not_enough(scorer: SignalScorer) -> None:
    assert scan(scorer, "Management cleared the backlog of unresolved staff comments.") == []


# --- the sentence's span ------------------------------------------------------------------------


def test_a_hit_is_the_text_at_its_span_with_the_typography_the_document_has(
    scorer: SignalScorer,
) -> None:
    text = (
        "Overview\n"
        "We had a good quarter. Customers can\u2019t get enough material from other vendors.\n"
        "Revenue rose.\n"
    )

    [hit] = scan(scorer, text)

    assert hit.quote == "Customers can\u2019t get enough material from other vendors."
    assert text[hit.start : hit.end] == hit.quote
    assert (hit.start, hit.end) == (32, 87)


def test_sentences_are_not_cut_at_abbreviations_initials_or_decimals() -> None:
    paragraph = (
        "Example Photonics Inc. sells in the U.S. and Japan. Line No. 5 is busy."
        " J. Smith said $10.5 million. Done."
    )

    cut = [paragraph[start:end] for start, end in sentence_spans(paragraph)]

    assert cut == [
        "Example Photonics Inc. sells in the U.S. and Japan.",
        "Line No. 5 is busy.",
        "J. Smith said $10.5 million.",
        "Done.",
    ]


def test_a_run_together_table_row_is_no_sentence(scorer: SignalScorer) -> None:
    row = "Backlog of $10 million " + "x " * 700

    assert scan(scorer, row) == []


# --- co-occurrence -----------------------------------------------------------------------------


def test_two_families_in_one_paragraph_each_get_the_bonus_but_not_across_paragraphs(
    scorer: SignalScorer,
) -> None:
    together = "Lead times have extended to 40 weeks. We are doubling our capacity."
    apart = "Lead times have extended to 40 weeks.\nWe are doubling our capacity."

    assert scored(scan(scorer, together)) == [
        ("Lead times have extended to 40 weeks.", 3.25),  # 1.5 + 0.75 + 1.0
        ("We are doubling our capacity.", 2.5),  # 1.5 + 1.0
    ]
    assert scored(scan(scorer, apart)) == [
        ("Lead times have extended to 40 weeks.", 2.25),
        ("We are doubling our capacity.", 1.5),
    ]


def test_a_bare_word_does_not_ride_on_its_neighbours_cue(scorer: SignalScorer) -> None:
    paragraph = (
        "Demand for our wafers is growing too fast, we cannot keep up, and only three"
        " suppliers make it. Management cleared the backlog of unresolved staff comments."
    )

    assert [hit.score for hit in scan(scorer, paragraph)] == [5.5]


# --- boilerplate and other senses --------------------------------------------------------------

RISK = "We depend on a sole source supplier for substrates and shortages could harm our business."
TEN_K = (
    "Item 1. Business\nWe make lasers.\nItem 1A. Risk Factors\n{risk}\nItem 2. Properties\n"
    "We lease.\n"
)


def test_risk_factor_wording_scores_under_the_same_words_elsewhere(scorer: SignalScorer) -> None:
    in_business = TEN_K.format(risk="").replace("We make lasers.\n", f"{RISK}\n")
    in_risk_factors = TEN_K.format(risk=RISK)

    business = scan(scorer, in_business, form_type="10-K", primary=True)
    risk_factors = scan(scorer, in_risk_factors, form_type="10-K", primary=True)

    # sole source 0.7 x 2.0 + shortages 0.4 x 2.0 + 1.0 = 3.2, hedged by "could": x 0.5 = 1.6;
    # in Item 1A also x 0.3 = 0.48, under the 1.5 threshold.
    assert [(hit.quote, hit.score, hit.section_anchor) for hit in business] == [
        (RISK, 1.6, "item-1")
    ]
    assert dict(business[0].factors) == {"families": 2.2, "cooccurrence": 1.0, "hedge": 0.5}
    assert risk_factors == []


def test_a_hedged_sentence_scores_under_the_same_one_unhedged(scorer: SignalScorer) -> None:
    assert scan(scorer, "Demand may exceed our supply.") == []
    assert scored(scan(scorer, "Demand exceeds our supply.")) == [
        ("Demand exceeds our supply.", 2.0)
    ]


def test_safe_harbor_wording_is_down_weighted(scorer: SignalScorer) -> None:
    sentence = (
        "This release contains forward-looking statements, including that our lasers are sold out"
        " through next year."
    )

    # sold out 2.0 + sold out through ... year 1.2 + 1.0 = 4.2, x 0.3 = 1.26.
    assert scan(scorer, sentence) == []
    assert scored(scan(scorer, "Our lasers are sold out through next year.")) == [
        ("Our lasers are sold out through next year.", 4.2)
    ]


@pytest.mark.parametrize(
    "sentence",
    [
        "The fund sold out of its position in the investee during the quarter.",
        "In his capacity as director he approved the software license agreement.",
        "Our capital allocation committee approved the purchase price allocation.",
        "Is the backlog of customer complaints something the board reviews?",
        "All performance obligations were fully met during the period.",
        "Customer demand was fully served from inventory in the quarter.",
        "We expect our net operating loss carryforwards to be fully utilized in 2026.",
        "The deferred tax assets were fully utilized in fiscal 2024.",
    ],
)
def test_a_family_word_in_another_sense_is_no_signal(scorer: SignalScorer, sentence: str) -> None:
    assert scan(scorer, sentence) == []


# --- negation (ticket 27) ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sentence",
    [
        "In the past the smaller wafers fell out of favor, so they are not sold out.",
        "We have no capacity constraints at any of our sites.",
        "We are not constrained by capacity this year.",
        "Our supply chain has not had any capacity constraints this year.",
        "We are running without any capacity constraints today.",
        "We don't see capacity constraints at the moment.",
        "Typically we do not have margin impacts from supply shortages here.",
    ],
)
def test_a_cue_a_negator_governs_is_no_match(scorer: SignalScorer, sentence: str) -> None:
    assert scan(scorer, sentence) == []


@pytest.mark.parametrize(
    "sentence",
    [
        "Demand does not exceed supply for our transceivers this year.",
        "Demand did not outstrip our capacity during the quarter at all.",
        "Our capacity is not constrained at this point in the year.",
        "Lead times have not lengthened for our customers this quarter.",
        "Lead times are no longer extended for most of our products now.",
    ],
)
def test_a_negator_inside_the_phrase_cancels_it(scorer: SignalScorer, sentence: str) -> None:
    assert scan(scorer, sentence) == []


@pytest.mark.parametrize(
    ("sentence", "score"),
    [
        ("Demand does exceed supply for our transceivers this year.", 2.0),
        ("Demand did outstrip our capacity during the quarter at all.", 2.0),
        ("Our capacity is constrained at this point in the year.", 1.5),
        ("Lead times have lengthened for our customers this quarter.", 1.5),
        ("Lead times are extended for most of our products now.", 1.5),
    ],
)
def test_the_same_sentence_without_the_inner_negator_keeps_its_score(
    scorer: SignalScorer, sentence: str, score: float
) -> None:
    [hit] = scan(scorer, sentence)

    assert hit.score == score


def test_not_only_inside_a_phrase_negates_nothing(scorer: SignalScorer) -> None:
    sentence = "Demand not only exceeds supply but keeps growing for our transceivers."

    assert scan(scorer, sentence) != []


@pytest.mark.parametrize(
    "sentence",
    [
        "We cannot keep up with orders.",
        "We can not keep up with orders.",
        "We can't get enough of these lasers for our customers.",
    ],
)
def test_cannot_keep_up_stays_a_match(scorer: SignalScorer, sentence: str) -> None:
    assert scan(scorer, sentence) != []


def test_the_same_words_without_the_negator_are_a_match(scorer: SignalScorer) -> None:
    sentence = "We have capacity constraints at several of our sites."

    # demand_beyond_supply "capacity constraints" 0.6 x 2.0 = 1.2, capacity "capacity
    # constraints" 1.5, and the paragraph shows both families: + 1.0.
    assert scored(scan(scorer, sentence)) == [(sentence, 3.7)]


def test_a_negation_leaves_the_other_cues_of_the_sentence(scorer: SignalScorer) -> None:
    sentence = "We have no capacity constraints, but lead times have extended to 40 weeks."

    [hit] = scan(scorer, sentence)

    assert (hit.families, hit.score) == (("lead_times_backlog",), 2.25)  # 1.5 + 0.75


def test_a_negator_reaches_to_the_end_of_its_list_but_not_into_the_next_clause(
    scorer: SignalScorer,
) -> None:
    list_ = "We have no capacity or supply constraints at any of our sites."
    clause = "We have no capacity constraints and lead times have extended to 40 weeks."

    assert scan(scorer, list_) == []
    [hit] = scan(scorer, clause)
    assert (hit.families, hit.score) == (("lead_times_backlog",), 2.25)  # 1.5 + 0.75


def test_the_abbreviation_no_is_no_negator(scorer: SignalScorer) -> None:
    sentence = "Line No. 5 is sold out through next year."

    assert scored(scan(scorer, sentence)) == [(sentence, 4.2)]  # 2.0 + 1.2 + 1.0


def test_a_negator_does_not_reach_across_a_clause_or_beyond_its_window(
    scorer: SignalScorer,
) -> None:
    clause = "We are not worried about the quarter, and our lasers are sold out through next year."
    far = "We never said that the fab was ever really sold out."

    # sold out 2.0 + sold out through ... year 1.2 + 1.0, then the same in "far": 2.0.
    assert scored(scan(scorer, clause)) == [(clause, 4.2)]
    assert scored(scan(scorer, far)) == [(far, 2.0)]


def test_not_only_and_no_matter_negate_nothing(scorer: SignalScorer) -> None:
    only = "Not only are our lasers sold out, demand keeps growing."
    matter = "Demand outpaces supply no matter how fast we add capacity."

    # demand outpaces supply 2.0; add capacity 0.5 x 1.5 = 0.75; two families: + 1.0.
    assert scored(scan(scorer, only)) == [(only, 2.0)]
    assert scored(scan(scorer, matter)) == [(matter, 3.75)]


def test_a_phrase_that_carries_its_own_negation_stays_a_match(scorer: SignalScorer) -> None:
    taking = "No we are not taking orders for the second half."
    adequately = "The market cannot be adequately served by one supplier."
    second = "There is no second source for this substrate."

    # An answer's "No" two words before "not taking orders": a plain phrase would be negated.
    assert scored(scan(scorer, taking)) == [(taking, 2.0)]
    assert scored(scan(scorer, adequately)) == [(adequately, 2.0)]
    assert scored(scan(scorer, second)) == [(second, 1.6)]  # 2.0 x 0.8


# --- pricing power is a price rise scarcity allows (ticket 27) ------------------------------------


@pytest.mark.parametrize(
    "sentence",
    [
        "We raised prices to offset higher input costs.",
        "On the input cost side, you have a price increase.",
        "We added a fuel surcharge and raised prices.",
        "We raised prices to cover inflation across our materials.",
        "We are passing through the tariff with a price increase to customers.",
        "Gross margin rose 250 basis points due to increased pricing on select products.",
        "Our supply agreements include clauses that allow annual price increases.",
        "We announced a price increase for the second half.",
    ],
)
def test_a_price_rise_that_recovers_a_cost_or_is_set_by_contract_is_no_pricing_power(
    scorer: SignalScorer, sentence: str
) -> None:
    assert scan(scorer, sentence) == []


@pytest.mark.parametrize(
    ("sentence", "score"),
    [
        ("Customers accept higher prices because supply is short.", 1.5),
        ("Our price increases stuck with every customer.", 1.5),
        ("We have real pricing power in this market.", 1.5),
        ("We have pricing power even as input costs rise.", 1.5),
        ("We announced a price increase of 12% for the second half.", 1.5),  # 0.75 + 0.75
    ],
)
def test_a_price_rise_demand_allows_is_pricing_power(
    scorer: SignalScorer, sentence: str, score: float
) -> None:
    assert scored(scan(scorer, sentence)) == [(sentence, score)]


# --- generic backlog and capacity lines (ticket 27) -----------------------------------------------


def test_record_backlog_alone_is_under_the_threshold_until_a_figure_or_a_second_family_backs_it(
    scorer: SignalScorer,
) -> None:
    alone = "We are entering the year with record backlog."
    figure = "We closed the year with record backlog, up 35%."
    second = "Our lasers are sold out and we have record backlog."

    assert scan(scorer, alone) == []  # 1.5 x 0.6 = 0.9
    assert scored(scan(scorer, figure)) == [(figure, 1.65)]  # 0.9 + 0.75
    assert scored(scan(scorer, second)) == [(second, 3.9)]  # 2.0 + 0.9 + 1.0


def test_adding_capacity_alone_is_under_the_threshold_until_a_figure_or_a_second_family_backs_it(
    scorer: SignalScorer,
) -> None:
    alone = "We are adding capacity to meet customer demand."
    figure = "We are adding capacity by 40% to meet demand."
    second = "We are adding capacity because of the industry shortage."

    assert scan(scorer, alone) == []  # 1.5 x 0.5 = 0.75
    assert scored(scan(scorer, figure)) == [(figure, 1.5)]  # 0.75 + 0.75
    assert scored(scan(scorer, second)) == [(second, 2.55)]  # 0.75 + 0.8 + 1.0


def test_a_generic_line_does_not_ride_on_its_neighbours_cue(scorer: SignalScorer) -> None:
    paragraph = "Our lasers are sold out through next year. We are adding capacity to meet demand."

    assert [hit.quote for hit in scan(scorer, paragraph)] == [
        "Our lasers are sold out through next year."
    ]


# --- the ranked read's cap on one document ------------------------------------------------------


def test_a_documents_hits_past_the_cap_come_after_the_rest_in_order() -> None:
    ranked = [("a", 9), ("a", 8), ("a", 7), ("a", 6), ("b", 5), ("a", 4), ("c", 3), ("b", 2)]

    assert cap_per_document(ranked, lambda each: each[0], 2) == [
        ("a", 9),
        ("a", 8),
        ("b", 5),
        ("c", 3),
        ("b", 2),
        ("a", 7),
        ("a", 6),
        ("a", 4),
    ]
    assert cap_per_document(ranked, lambda each: each[0], 99) == ranked
    assert cap_per_document([], lambda each: each, 3) == []


# --- who speaks --------------------------------------------------------------------------------

CEO = "Alex Example (CEO, Example Photonics Inc)"
ANALYST = "Sam Sample (Managing Director and Equity Research Analyst, Example Securities)"
SOLD_OUT = "our indium phosphide lasers are sold out through the end of the year."
CALL = (
    "Operator: Welcome to the call.\n"
    f"{CEO}: Thank you. Yes, {SOLD_OUT}\n"
    f"{ANALYST}: Your indium phosphide lasers are sold out through the end of the year.\n"
    f"{ANALYST}: Are your indium phosphide lasers sold out through the end of the year?\n"
    f"Operator: Note that {SOLD_OUT}\n"
)


def test_the_companys_own_people_score_above_an_analyst_and_a_question_scores_below(
    scorer: SignalScorer,
) -> None:
    hits = scan(scorer, CALL, source_type="transcript")

    # sold out 2.0 + sold out through ... year 1.2 + 1.0 = 4.2; management x 1.25, a speaker
    # with no affiliation x 0.8, an analyst's statement x 0.5; an analyst's question x 0.5 x 0.6
    # is 1.26, under the threshold.
    assert [(hit.quote, hit.score, hit.speaker, hit.speaker_kind) for hit in hits] == [
        (f"Yes, {SOLD_OUT}", 5.25, CEO, "management"),
        (f"Note that {SOLD_OUT}", 3.36, "Operator", "unknown"),
        (
            "Your indium phosphide lasers are sold out through the end of the year.",
            2.1,
            ANALYST,
            "analyst",
        ),
    ]
    assert all(CALL[hit.start : hit.end] == hit.quote for hit in hits)
    assert not any("Are your" in hit.quote for hit in hits)


def test_outside_a_transcript_nobody_is_a_speaker(scorer: SignalScorer) -> None:
    hits = scan(scorer, CALL, source_type="8-K")

    assert {hit.speaker_kind for hit in hits} == {None}


# --- the config --------------------------------------------------------------------------------


def test_the_checked_in_config_is_valid() -> None:
    config = load_signals_config(CONFIG)

    assert config.version == 2
    assert config.ranking.max_per_document == 3
    assert config.negation.window_words == 4
    assert list(config.families) == [
        "few_suppliers",
        "demand_beyond_supply",
        "lead_times_backlog",
        "capacity",
        "gates",
        "pricing_power",
    ]


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "signals.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_a_missing_file_is_refused(tmp_path: Path) -> None:
    with pytest.raises(SignalsConfigError, match=r"signals\.yaml"):
        load_signals_config(tmp_path / "signals.yaml")


def test_a_weight_out_of_range_is_refused(tmp_path: Path) -> None:
    text = CONFIG.read_text(encoding="utf-8").replace("weight: 2.0", "weight: 0", 1)

    with pytest.raises(SignalsConfigError, match="weight"):
        load_signals_config(write(tmp_path, text))


def test_a_pattern_that_is_not_a_regular_expression_is_refused(tmp_path: Path) -> None:
    text = CONFIG.read_text(encoding="utf-8").replace(r"\bduopol(?:y|ist)\b", r"\bduopol(?:y|ist\b")

    with pytest.raises(SignalsConfigError, match="not a regular expression"):
        load_signals_config(write(tmp_path, text))


def test_an_unknown_key_is_refused(tmp_path: Path) -> None:
    text = CONFIG.read_text(encoding="utf-8").replace("min_score: 1.5", "min_score: 1.5\nbonus: 3")

    with pytest.raises(SignalsConfigError, match="bonus"):
        load_signals_config(write(tmp_path, text))


def test_a_family_name_must_be_snake_case(tmp_path: Path) -> None:
    text = CONFIG.read_text(encoding="utf-8").replace("  few_suppliers:", "  Few-Suppliers:")

    with pytest.raises(SignalsConfigError, match="snake_case"):
        load_signals_config(write(tmp_path, text))


def test_the_negation_and_ranking_blocks_are_checked(tmp_path: Path) -> None:
    text = CONFIG.read_text(encoding="utf-8")

    with pytest.raises(SignalsConfigError, match="window_words"):
        load_signals_config(write(tmp_path, text.replace("window_words: 4", "window_words: 0")))
    with pytest.raises(SignalsConfigError, match="max_per_document"):
        load_signals_config(
            write(tmp_path, text.replace("max_per_document: 3", "max_per_document: 0"))
        )
    with pytest.raises(SignalsConfigError, match="ranking"):
        load_signals_config(write(tmp_path, text.replace("ranking:\n  max_per_document: 3\n", "")))
