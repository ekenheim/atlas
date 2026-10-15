"""Where a quote is in an archived parse: the rule `atlas_tools.py` applied on the client, now
the server's (atlas-beliefs ticket 15)."""

from dataclasses import dataclass
from typing import Literal

from atlas.claims.predicates import fold

type OffsetSource = Literal["exact", "folded"]


@dataclass(frozen=True)
class Located:
    start: int
    end: int
    source: OffsetSource
    archived_quote: str  # the parse's own text at the span


@dataclass(frozen=True)
class NotLocated:
    reason: Literal["quote_not_found", "quote_ambiguous"]
    occurrences: int


def locate_quote(text: str, quote: str) -> Located | NotLocated:
    """The one place `quote` occurs in `text` (code-point offsets): its exact text, else the
    same text through the typographic fold (one character to one character, so the offsets
    hold in the original). No occurrence, or more than one, is not located."""
    quote = quote.strip()
    if not quote:
        return NotLocated("quote_not_found", 0)
    source: OffsetSource = "exact"
    count = text.count(quote)
    start = text.find(quote)
    if count == 0:
        folded_text, folded_quote = fold(text), fold(quote)
        count = folded_text.count(folded_quote)
        start = folded_text.find(folded_quote)
        source = "folded"
    if count != 1:
        return NotLocated("quote_not_found" if count == 0 else "quote_ambiguous", count)
    end = start + len(quote)
    return Located(start, end, source, text[start:end])
