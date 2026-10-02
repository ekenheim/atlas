"""Who says a transcript's words (pilot-fixes ticket 22): the speaker rule over the label shapes
production transcripts carry, written synthetically ("Name (Title, Firm)" for a company's
officers and for analysts, a title with several commas, "Operator" and a bare name alone)."""

import pytest

from atlas.claims.speakers import SpeakerRefusal, speaker_label, transcript_speaker

NAMES = ["Example Photonics Holdings Inc.", "Example Photonics Holdings", "Example Photonics"]


def spoken(label: str, words: str = "We are doubling our substrate capacity this year.") -> str:
    return f"{label}: {words}\n"


def speaker(text: str, quote: str) -> str | SpeakerRefusal:
    start = text.index(quote)
    return transcript_speaker(text, (start, start + len(quote)), NAMES)


@pytest.mark.parametrize(
    "label",
    [
        "Alex Example (President and CEO, Example Photonics Holdings Inc)",
        "Alex Example (CEO, Example Photonics)",
        "Robin Placeholder (VP of Business Development, Strategic Sales, and Marketing,"
        " Example Photonics)",
        "Robin Placeholder (CEO, President, Chairman, Example Photonics)",
        "Kim Sample (VP of Investor Relations, Example Photonics Holdings Inc)",
    ],
)
def test_the_companys_officers_speak_for_it(label: str) -> None:
    text = spoken("Operator", "Our next question.") + spoken(label)

    assert speaker(text, "doubling our substrate capacity") == label


@pytest.mark.parametrize(
    "label",
    [
        "Sam Sample (Analyst, Example Bank)",
        "Sam Sample (Managing Director and Equity Research Analyst, Example Securities)",
        "Sam Sample (Managing Director, Senior Semiconductor Analyst, Example Financial)",
        "Sam Sample (Managing Director, Example Research)",
        "Sam Sample (Head of Hardware Equity Research, Example Bank)",
    ],
)
def test_an_analyst_or_another_firm_is_not_the_company(label: str) -> None:
    text = spoken(label)

    said = speaker(text, "doubling our substrate capacity")

    assert isinstance(said, SpeakerRefusal)
    assert said.code == "analyst_speaking"
    assert label in said.message


@pytest.mark.parametrize("label", ["Operator", "Alex Example", "Alex Example (CEO)"])
def test_a_label_without_an_affiliation_is_unknown(label: str) -> None:
    said = speaker(spoken(label), "doubling our substrate capacity")

    assert isinstance(said, SpeakerRefusal) and said.code == "speaker_unknown"


def test_a_paragraph_without_a_label_is_unknown() -> None:
    text = spoken("Alex Example (CEO, Example Photonics)", "We said so.\nthe line goes on")

    said = speaker(text, "the line goes on")

    assert isinstance(said, SpeakerRefusal) and said.code == "speaker_unknown"


def test_a_quote_over_two_speakers_is_mixed() -> None:
    officer = "Alex Example (CEO, Example Photonics)"
    analyst = "Sam Sample (Analyst, Example Bank)"
    text = spoken(officer, "Capacity doubles.") + spoken(analyst, "Thank you, and capacity?")

    said = speaker(text, f"doubles.\n{analyst}: Thank you")

    assert isinstance(said, SpeakerRefusal) and said.code == "speaker_mixed"
    assert officer in said.message and analyst in said.message


def test_the_label_is_the_line_start_up_to_its_colon() -> None:
    assert speaker_label("Alex Example (CEO, Example Photonics): Thanks: all.") == (
        "Alex Example (CEO, Example Photonics)"
    )
    assert speaker_label("Operator: Welcome.") == "Operator"
    assert speaker_label("the largest customer?") is None
