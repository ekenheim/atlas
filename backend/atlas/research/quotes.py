"""Quote validation for research answers: the one normalization rule (spec Part B story 20).

A quote in an answer counts only if it occurs in the archived parsed text of a cited section
after normalizing **exactly two things** on both sides (rule `QUOTE_RULE`):

1. typographic quotes: U+2018, U+2019, U+201A and U+201B become ' and U+201C, U+201D,
   U+201E and U+201F become "
2. whitespace: every run of whitespace characters (`str.isspace`, so also newlines and
   no-break spaces) becomes one space, and the quote's leading and trailing whitespace is
   dropped

Nothing else is forgiven: case, punctuation, dashes, ellipses, digits and word order must
match, so a paraphrase can't pass as a quotation. A matched quote is reported as the span of
the original (un-normalized) parsed text it covers, in code points, like an Assertion's
offsets.

Quotes are the double-quoted passages of the answer text, straight or typographic (U+201C
... U+201D), on one line. Single quotes are not treated as quotation marks (they are also
apostrophes).
"""

import re
from dataclasses import dataclass

QUOTE_RULE = "whitespace-and-typographic-quotes-v1"

_TYPOGRAPHIC = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u201a": "'",
        "\u201b": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u201e": '"',
        "\u201f": '"',
    }
)
_QUOTED = re.compile(r"\u201c([^\u201d\n]+)\u201d|\"([^\"\n]+)\"")


@dataclass(frozen=True)
class Normalized:
    """Normalized text and, for each of its characters, the original index it came from."""

    text: str
    origins: tuple[int, ...]


def normalize(original: str) -> Normalized:
    chars: list[str] = []
    origins: list[int] = []
    in_space = False
    for index, char in enumerate(original):
        if char.isspace():
            if not in_space:
                chars.append(" ")
                origins.append(index)
            in_space = True
            continue
        in_space = False
        chars.append(char.translate(_TYPOGRAPHIC))
        origins.append(index)
    return Normalized("".join(chars), tuple(origins))


def normalize_quote(quote: str) -> str:
    return normalize(quote).text.strip(" ")


def extract_quotes(answer: str) -> list[str]:
    """The distinct double-quoted passages of an answer, in order of first appearance."""
    quotes: list[str] = []
    for match in _QUOTED.finditer(answer):
        quote = (match.group(1) or match.group(2)).strip()
        if any(char.isalnum() for char in quote) and quote not in quotes:
            quotes.append(quote)
    return quotes


def find_quote(quote: str, text: str, *, offset: int = 0) -> tuple[int, int] | None:
    """The [start, end) span of `text` the quote matches under the rule, plus `offset`."""
    needle = normalize_quote(quote)
    if not needle:
        return None
    haystack = normalize(text)
    at = haystack.text.find(needle)
    if at < 0:
        return None
    start = haystack.origins[at]
    end = haystack.origins[at + len(needle) - 1] + 1
    return offset + start, offset + end
