"""`atlas.facts.reuse.same_statement` (atlas-beliefs ticket 28): the words alone, with case,
whitespace and punctuation normalised; a figure, a sign, a currency or one word more is another
statement. The HTTP-seam tests are in `tests/integration/test_judged_at_record.py` and
`test_mcp_server.py`."""

import pytest

from atlas.facts.reuse import same_statement


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("Net revenue was $1.01 billion.", "net  revenue was $1.01 billion"),
        ("Lumentum\N{RIGHT SINGLE QUOTATION MARK}s revenue rose.", "Lumentum's revenue rose"),
        ("A fourth-quarter figure.", "a fourth\N{NON-BREAKING HYPHEN}quarter figure"),
        ("Margin was -5%.", "MARGIN WAS \N{MINUS SIGN}5%"),
    ],
)
def test_statements_equal_after_case_whitespace_and_punctuation(a: str, b: str) -> None:
    assert same_statement(a, b)


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("the merchant indium phosphide market", "the market"),
        ("Revenue was $1.01 billion.", "Revenue was 1.01 billion."),
        ("Revenue was $1.01 billion.", "Revenue was €1.01 billion."),
        ("Revenue was 1.01 billion.", "Revenue was 101 billion."),
        ("Revenue was 1.01 billion.", "Revenue was 1,01 billion."),
        ("Margin was -5%.", "Margin was 5%."),
        ("Margin was 5%.", "Margin was 5 points."),
        ("Revenue was >$1 billion.", "Revenue was $1 billion."),
        ("Revenue was ~$1 billion.", "Revenue was $1 billion."),
        ("Margin was ≥5%.", "Margin was ≤5%."),
    ],
)
def test_one_word_figure_sign_or_currency_apart_is_another_statement(a: str, b: str) -> None:
    assert not same_statement(a, b)
