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

    assert config.version == 1
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
