"""The sentence patterns of the mechanical bear checks (Chokepoint Watch ticket W4).

Pure functions over a parsed text (no database, no model): each returns the sentences that
match, with their span as code points into that text, so a match can be quoted and checked the
way an Assertion's span is. The patterns live here and nowhere else; `atlas.bear_checks.service`
decides what a match means.

- **Customer concentration**: "accounted for (approximately) 32% of our net revenue" and the
  close variants a filing uses ("represented", "comprised", "constituted", "contributed", a list
  of years "12%, 15% and 22%", "of total revenues", "of net sales", "approximately 30% of our
  revenue was derived from"). A sentence is one match whatever the number of its percentages.
- **Going concern**: "substantial doubt about our / the Company's / its ability to continue as a
  going concern". A sentence that negates it ("did not raise", "no substantial doubt",
  "alleviated", "does not exist") is returned with `negated` set; one that only imagines it
  ("could raise") with `hedged`.
"""

import re
from collections.abc import Iterator
from dataclasses import dataclass
from decimal import Decimal

_NUMBER = r"\d{1,3}(?:\.\d+)?"
_APPROX = (
    r"(?:approximately|about|roughly|nearly|over|more\s+than|an\s+aggregate\s+of"
    r"|in\s+excess\s+of|at\s+least)"
)
_PERCENT = rf"(?:{_APPROX}\s+)?{_NUMBER}\s*%"
_PERCENT_LIST = rf"{_PERCENT}(?:\s*(?:,\s*)?(?:,|and|or)\s+{_PERCENT})*"
_VERB = r"(?:accounted\s+for|represent(?:ed|s|ing)|comprised|constituted|contributed|made\s+up)"
_OWNER = (
    r"(?:(?:our|the\s+company['\u2019]s|its|total|consolidated|net|aggregate|combined|annual)\s+)*"
)
_REVENUE = r"(?:net\s+|total\s+)*(?:revenues?|sales)"

_ACCOUNTED = re.compile(
    rf"{_VERB}\s+(?:for\s+)?(?P<list>{_PERCENT_LIST})\s+of\s+{_OWNER}{_REVENUE}", re.I
)
_DERIVED = re.compile(
    rf"(?P<list>{_PERCENT})\s+of\s+{_OWNER}{_REVENUE}\s+(?:was|were)\s+"
    r"(?:derived\s+from|attributable\s+to|generated\s+(?:by|from)|from)",
    re.I,
)
# A share of revenue is a customer's when the sentence says so; one about a region, a country or
# where a product is shipped is not ("customers outside the United States ... 79.2% of net
# revenue" is geography, not concentration).
_CUSTOMER = re.compile(
    r"\b(?:customers?|distributors?|resellers?|clients?|channel\s+partners?|oems?)\b"
    r"|\bsales\s+to\b",
    re.I,
)
_GEOGRAPHY = re.compile(
    r"\boutside\b|\bgeograph\w*|\bregions?\b|\bcountr(?:y|ies)\b|\blocated\s+in\b"
    r"|\bbased\s+in\b|\bshipped\s+to\b|\binternational\b|\bdomestic\b|\bforeign\b",
    re.I,
)
_NUMBERS = re.compile(rf"({_NUMBER})\s*%")
# A table row of the customer note: "Customer A<tab>26.6<tab>%<tab>15.4<tab>%" (the parse keeps a
# table's cells on one line, tab-separated). Only under a revenue heading, not a receivables one.
_ROW = re.compile(
    r"^[ \t]*(?:customers?|distributors?|resellers?|clients?|oems?)\s+(?:[A-Z]|\d{1,2})\b[^\n]*$",
    re.I | re.M,
)
_REVENUE_WORD = re.compile(r"\b(?:revenues?|sales)\b", re.I)
_RECEIVABLES_WORD = re.compile(r"\breceivables?\b", re.I)
_ROW_CONTEXT = 1200

_GOING_CONCERN = re.compile(
    r"substantial\s+doubt\s+(?:about|regarding|as\s+to|concerning|over)\s+"
    r"(?:our|its|the\s+company['\u2019]s|[A-Z][\w.&\- ]{0,40}?['\u2019]s)\s+"
    r"ability\s+to\s+continue\s+as\s+a\s+going\s+concern",
    re.I,
)
_NEGATION_BEFORE = re.compile(
    r"\b(?:no|not|never|without|nor|alleviat\w+|dispel\w*|eliminat\w+|overcom\w+)\b", re.I
)
_NEGATION_AFTER = re.compile(
    r"\b(?:does|do|did)\s+not\s+(?:exist|raise)\b|\bno\s+longer\b|\b(?:has|have|had|was|were)\s+been\s+"
    r"(?:alleviated|dispelled|eliminated|removed)\b|\bwas\s+alleviated\b",
    re.I,
)
_HEDGE_BEFORE = re.compile(r"\b(?:could|may|might|would|if|whether|potential(?:ly)?)\b", re.I)

# A sentence ends at a full stop, "?" or "!" (and any closing quote or bracket) before a space,
# or at a line break; a full stop after one of these abbreviations does not end it.
_BOUNDARY = re.compile(r"(?<=[.!?])[\"')\]\u201d\u2019]*\s+|\n+")
_ABBREVIATIONS = frozenset(
    {"inc", "corp", "co", "ltd", "no", "nos", "u.s", "vs", "e.g", "i.e", "approx", "mr", "dr", "st"}
)
_WINDOW = 800


@dataclass(frozen=True)
class SentenceMatch:
    """A sentence that matches a pattern: `text[char_start:char_end] == sentence`."""

    char_start: int
    char_end: int
    sentence: str


@dataclass(frozen=True)
class ConcentrationMatch(SentenceMatch):
    percents: tuple[Decimal, ...]

    @property
    def maximum(self) -> Decimal:
        return max(self.percents)


@dataclass(frozen=True)
class GoingConcernMatch(SentenceMatch):
    negated: bool
    hedged: bool


def sentence_span(text: str, start: int, end: int) -> tuple[int, int]:
    """The span of the sentence containing `text[start:end]`, whitespace trimmed."""
    low, high = max(0, start - _WINDOW), min(len(text), end + _WINDOW)
    left, right = low, high
    for boundary in _boundaries(text, low, high):
        if boundary.end() <= start:
            left = boundary.end()
        elif boundary.start() >= end:
            right = boundary.start()
            break
    while left < right and text[left].isspace():
        left += 1
    while right > left and text[right - 1].isspace():
        right -= 1
    return left, right


def _boundaries(text: str, low: int, high: int) -> Iterator[re.Match[str]]:
    for boundary in _BOUNDARY.finditer(text, low, high):
        word = re.search(r"([\w.]+)\.$", text[max(low, boundary.start() - 12) : boundary.start()])
        if word and word.group(1).lower() in _ABBREVIATIONS and "\n" not in boundary.group():
            continue
        yield boundary


def customer_concentration(text: str) -> list[ConcentrationMatch]:
    """The sentences that say a customer "accounted for" N% of revenue, in text order, and the
    rows of a table that give customers' percentages ("Customer A  26.6 %  15.4 %"); the
    percentages of one sentence or row are one match. A sentence must name a customer (or a
    distributor, reseller, OEM, "sales to ...") and not a region or country; a row must follow
    a mention of revenue or sales with no mention of receivables after it."""
    found: dict[tuple[int, int], list[Decimal]] = {}
    for row in _ROW.finditer(text):
        numbers = [Decimal(each) for each in _NUMBERS.findall(row.group())]
        if numbers and _revenue_table(text, row.start()):
            found.setdefault((row.start(), row.end()), []).extend(numbers)
    for pattern in (_ACCOUNTED, _DERIVED):
        for match in pattern.finditer(text):
            span = sentence_span(text, match.start(), match.end())
            sentence = text[span[0] : span[1]]
            if not _CUSTOMER.search(sentence) or _GEOGRAPHY.search(sentence):
                continue
            numbers = [Decimal(each) for each in _NUMBERS.findall(match.group("list"))]
            found.setdefault(span, []).extend(numbers)
    return [
        ConcentrationMatch(start, end, text[start:end], tuple(sorted(set(numbers))))
        for (start, end), numbers in sorted(found.items())
        if any(Decimal(0) <= each <= Decimal(100) for each in numbers)
    ]


def _revenue_table(text: str, position: int) -> bool:
    """Whether the rows at `position` follow a revenue (or sales) heading, not a receivables
    one: the last such word before them, within a page, is not "receivable"."""
    context = text[max(0, position - _ROW_CONTEXT) : position]
    revenue = [m.start() for m in _REVENUE_WORD.finditer(context)]
    receivables = [m.start() for m in _RECEIVABLES_WORD.finditer(context)]
    return bool(revenue) and (not receivables or max(revenue) > max(receivables))


def going_concern(text: str) -> list[GoingConcernMatch]:
    """The sentences that name substantial doubt about continuing as a going concern, in text
    order, each marked `negated` (the sentence says there is none) or `hedged` (it says there
    could be)."""
    found: list[GoingConcernMatch] = []
    seen: set[tuple[int, int]] = set()
    for match in _GOING_CONCERN.finditer(text):
        start, end = sentence_span(text, match.start(), match.end())
        if (start, end) in seen:
            continue
        seen.add((start, end))
        before = text[start : match.start()]
        after = text[match.end() : end]
        negated = bool(_NEGATION_BEFORE.search(before[-80:]) or _NEGATION_AFTER.search(after))
        hedged = bool(_HEDGE_BEFORE.search(before))
        found.append(GoingConcernMatch(start, end, text[start:end], negated, hedged))
    return found
