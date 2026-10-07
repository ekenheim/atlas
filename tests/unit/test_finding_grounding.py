"""The grounding check of a research card's findings (pilot-fixes ticket 21): every number,
capitalised name and quoted phrase of a finding's statement must occur in the Claims it cites.

Seam: `atlas.investigations.grounding` (`grounds`, `claim_grounds`, `ungrounded`), a pure
function of text. The quotes are synthetic, shaped like the pilot's (a call transcript, a
results release, an 8-K); none is production text.
"""

from collections.abc import Sequence

from atlas.investigations.grounding import claim_grounds, grounds, ungrounded

RELEASE = (
    "Net proceeds from the offering were $412.5 million, and we issued 18,250,000 new shares"
    " at $23.10 per share; gross margin was 41.2% in the second quarter of fiscal 2026."
)
CALL = (
    "We are sold out in our Rosemont fab through the first half of 2027, and we are adding"
    " 6-inch indium phosphide capacity at our site in Orleans, France."
)
AGREEMENT = (
    "On May 14, 2026, Zephyr Optics Inc. entered into a Master Supply Agreement with Halcyon"
    " Networks for 200G EMLs with a three (3) year initial term."
)


def check(
    statement: str, *texts: str, question: str = "", aliases: Sequence[Sequence[str]] = ()
) -> list[str]:
    return ungrounded(statement, grounds([question, *texts], aliases))


# --- numbers ------------------------------------------------------------------------------------


def test_amounts_with_currency_signs_separators_and_magnitudes_are_found_by_value() -> None:
    assert check("Net proceeds were $412.5 million.", RELEASE) == []
    assert check("Net proceeds were $412.5m.", RELEASE) == []
    assert check("Net proceeds were $412,500,000.", RELEASE) == []
    assert check("It issued 18,250,000 shares at $23.10.", RELEASE) == []
    assert check("It issued 18.25 million shares.", RELEASE) == []


def test_an_amount_no_cited_quote_states_is_ungrounded_as_written() -> None:
    assert check("Net proceeds were $600.1 million.", RELEASE) == ["$600.1 million"]
    assert check("It raised £81m by issuing 332,183,678 shares.", RELEASE) == [
        "£81m",
        "332,183,678",
    ]


def test_a_currency_must_agree_when_both_sides_name_one() -> None:
    assert check("Net proceeds were £412.5 million.", RELEASE) == ["£412.5 million"]


def test_percentages_must_match_and_a_unit_is_not_another() -> None:
    assert check("Gross margin was 41.2%.", RELEASE) == []
    assert check("Gross margin was 41.2 percent.", RELEASE) == []
    assert check("Gross margin was 43%.", RELEASE) == ["43%"]
    assert check("It sells 200G EMLs.", AGREEMENT) == []
    assert check("It sells 200% more EMLs.", AGREEMENT) == ["200%"]


def test_dates_years_and_quarters() -> None:
    assert check("The agreement was signed on May 14, 2026.", AGREEMENT) == []
    assert check("The agreement was signed on May 15, 2026.", AGREEMENT) == ["15"]
    assert check("The agreement was signed on June 14, 2026.", AGREEMENT) == ["June"]
    # "the second quarter of fiscal 2026" is Q2 and FY2026; "the first half of 2027" is H1.
    assert check("Margin was 41.2% in Q2 FY2026.", RELEASE) == []
    assert check("It is sold out through H1 2027.", CALL) == []
    assert check("It is sold out through 1H 2028.", CALL) == ["2028"]
    assert check("It is sold out through Q3 2027.", CALL) == ["Q3"]


def test_a_number_word_in_the_quote_grounds_the_digit() -> None:
    assert check("The agreement has a 3-year initial term.", AGREEMENT) == []


def test_a_year_in_the_question_is_allowed() -> None:
    question = "Who is adding InP capacity for 2028?"
    assert check("Rosemont adds capacity for 2028.", CALL) == ["2028"]
    assert check("Rosemont adds capacity for 2028.", CALL, question=question) == []


# --- names --------------------------------------------------------------------------------------


def test_a_place_or_company_no_cited_quote_names_is_ungrounded() -> None:
    assert check("It is adding capacity in Orleans, France.", CALL) == []
    assert check("It is adding capacity in Lyon, France and in Austin.", CALL) == [
        "Lyon",
        "Austin",
    ]
    # Neighbouring words are one name; punctuation ends one.
    assert check("Its customer Bellweather Systems is in Zurich, Switzerland.", CALL) == [
        "Bellweather Systems",
        "Zurich",
        "Switzerland",
    ]


def test_a_sentence_starting_with_an_invented_name_is_caught() -> None:
    assert check("Covert is Zephyr's laser customer for Halcyon.", AGREEMENT) == ["Covert"]


def test_function_words_and_quoted_words_that_start_a_sentence_are_not_names() -> None:
    assert check("However, the Rosemont fab is sold out. The site is in France.", CALL) == []


def test_multi_word_names_found_in_the_quote_are_grounded_as_a_whole() -> None:
    statement = "Zephyr Optics signed a Master Supply Agreement with Halcyon Networks."
    assert check(statement, AGREEMENT) == []
    assert check("Zephyr signed with Bank of Ruritania.", AGREEMENT) == ["Bank of Ruritania"]


def test_plurals_possessives_and_alphanumeric_names() -> None:
    assert check("Halcyon's supplier sells EMLs.", AGREEMENT) == []
    assert check("Halcyon buys GB300 parts.", AGREEMENT) == ["GB300"]


def test_a_display_name_where_the_quote_has_the_legal_name_is_grounded() -> None:
    # A company's display and legal names (the `company` table's) are one name.
    names = [("QPL", "Quantum Photonic Lasers Corp."), ("Halcyon", "Halcyon Networks Ltd.")]
    legal = "Quantum Photonic Lasers Corp. ships 200G EMLs to Halcyon Networks Ltd."
    assert check("QPL ships 200G EMLs to Halcyon.", legal) == ["QPL"]
    assert check("QPL ships 200G EMLs to Halcyon.", legal, aliases=names) == []
    # The legal name without its suffix, as a transcript says it.
    spoken = "Quantum Photonic Lasers ships 200G EMLs."
    assert check("QPL ships 200G EMLs.", spoken, aliases=names) == []
    # And the other way round: the legal name in the statement, the display name quoted.
    quote = "QPL ships 200G EMLs to Halcyon."
    statement = "Quantum Photonic Lasers Corp. ships to Halcyon Networks Ltd."
    assert check(statement, quote, aliases=names) == []
    assert check("QPL ships to Halcyon Networks.", quote) == ["Networks"]


def test_domain_abbreviations_count_as_their_long_form() -> None:
    assert check("Rosemont adds 6-inch InP capacity.", CALL) == []
    assert check("Rosemont adds 6-inch GaAs capacity.", CALL) == ["GaAs"]


def test_short_acronyms_keep_their_case() -> None:
    # "us" in a quote is a pronoun, not the United States.
    quote = "Customers ask us for more lasers."
    assert check("Customers ask the US for more lasers.", quote) == ["US"]


# --- quoted phrases and the typographic fold ----------------------------------------------------


def test_a_quoted_phrase_must_be_copied_from_a_cited_quote() -> None:
    assert check('Rosemont is "sold out in our Rosemont fab".', CALL) == []
    assert check('It says it is "sold out ... through the first half of 2027".', CALL) == []
    assert check('It reports "200G-per-lane EMLs".', AGREEMENT) == ['"200G-per-lane EMLs"']


def test_the_fold_handles_typographic_quotes_hyphens_and_spaces() -> None:
    left, right = "\N{LEFT DOUBLE QUOTATION MARK}", "\N{RIGHT DOUBLE QUOTATION MARK}"
    curly = (
        f"We\N{RIGHT SINGLE QUOTATION MARK}re {left}sold out{right} in our Rosemont"
        " fab\N{EM DASH}through 2027."
    )
    assert check('Rosemont is "sold out" through 2027.', curly) == []
    assert check(f"Rosemont is {left}sold out{right} through 2027.", CALL) == []
    assert check("It adds 6\N{NON-BREAKING HYPHEN}inch capacity at Orleans.", CALL) == []
    assert check("Net proceeds were $412.5\N{NO-BREAK SPACE}million.", RELEASE) == []


# --- what a finding is held to: its own Claims ----------------------------------------------------


def test_a_finding_is_held_to_its_cited_claims_subjects_objects_and_sources() -> None:
    zephyr = {
        "quote": "we entered into a supply agreement for 200G EMLs",
        "subject_name": "Zephyr",
        "object_name": "Halcyon",
        "object_text": None,
        "source_title": "Zephyr Optics Q3 2025 Earnings Call",
    }
    statement = "Zephyr supplies Halcyon with 200G EMLs (Q3 2025)."
    assert ungrounded(statement, claim_grounds("Who supplies EMLs?", [zephyr])) == []
    # Another finding's Claim names Zurich; this one's don't.
    assert ungrounded(
        "Zephyr supplies Halcyon from Zurich.", claim_grounds("Who supplies EMLs?", [zephyr])
    ) == ["Zurich"]


# --- punctuation, claim labels and nested quotes (pilot-fixes ticket 33) -------------------------

SUPPLY = (
    'Our wafers come from Orchid Semiconductor Company Limited ("OSC"), our sole source'
    " foundry, and we use advanced packaging to produce highly capable TIAs and drivers."
)


def test_punctuation_at_the_ends_of_a_quoted_phrase_does_not_matter() -> None:
    assert check('It makes "highly capable TIAs and drivers,"', SUPPLY) == []
    assert check('It makes "highly capable TIAs and drivers"', SUPPLY) == []
    assert check('It has a "sole source foundry;"', SUPPLY) == []


def test_a_changed_word_in_a_quoted_phrase_still_fails() -> None:
    assert check('It makes "highly capable TIAs and lasers,"', SUPPLY) == [
        '"highly capable TIAs and lasers,"'
    ]
    assert check('It makes "highly capable TIAs, and drivers."', SUPPLY) != []


def test_the_editors_claim_labels_are_not_figures() -> None:
    assert check("Orchid is the sole source foundry (c10, c15).", SUPPLY) == []
    assert check("Orchid is the sole source foundry (c4).", SUPPLY) == []
    assert check("Orchid is the sole source foundry, as c4 and c5 say.", SUPPLY) == []
    # A figure next to a label is still checked.
    assert check("Orchid is the sole source foundry for 40% (c4).", SUPPLY) == ["40%"]


def test_a_label_the_grounds_themselves_contain_stays_a_term() -> None:
    assert check("The part c10 is named.", "The c10 part is a connector.") == []


def test_a_nested_quotation_of_the_other_kind_or_escaped_still_matches() -> None:
    both = [
        "It says \"Orchid Semiconductor Company Limited ('OSC'), our sole source foundry,\"",
        'It says "Orchid Semiconductor Company Limited (\\"OSC\\"), our sole source foundry,"',
        'It says "Orchid Semiconductor Company Limited ("OSC"), our sole source foundry,"',
    ]
    for statement in both:
        assert check(statement, SUPPLY) == [], statement
    assert (
        check(
            "It says \"Orchid Semiconductor Company Limited ('OSX'), our sole source foundry,\"",
            SUPPLY,
        )
        != []
    )


def test_an_ellipsis_and_a_bracketed_letter_still_split_a_phrase_into_pieces() -> None:
    assert (
        check('It says "[o]ur wafers come from Orchid... our sole source foundry,"', SUPPLY) == []
    )
    assert check('It says "wafers come from Orchid... our only foundry,"', SUPPLY) != []
