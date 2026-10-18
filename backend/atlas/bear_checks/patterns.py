"""The sentence patterns of the mechanical bear checks (Chokepoint Watch ticket W4).

Pure functions over a parsed text (no database, no model): each returns the sentences (or table
rows) that match, with their span as code points into that text, so a match can be quoted and
checked the way an Assertion's span is. The patterns live here and nowhere else;
`atlas.bear_checks.service` decides what a match means. The rule behind them: a match is
evidence only of what it says, and a check may say `clear` only on positive evidence.

- **Customer concentration**: "accounted for (approximately) 32% of our net revenue" and the
  close variants a filing uses ("represented", "comprised", "constituted", "contributed", "32
  percent", a list "12%, 15% and 22%", "of total revenues", "of net sales", "approximately 30%
  of our revenue was derived from"), and the rows of a customer revenue table. A match records
  the percentages as written and the current period's (the first column, unless the years run
  oldest first), never the largest. "More than 10%" and "10% or more" are lower bounds
  (`floor`). A region or country as the subject is not a customer ("Customers in China", "outside
  the United States") unless a customer is named; "our ten largest customers" is a group
  (`top_customers`), not one customer.
- **No large customer**: "No single customer accounted for more than 10% of our revenue", the one
  sentence that is positive evidence of no concentration.
- **Going concern**: "substantial doubt about our / its / the Company's ability to continue as a
  going concern", "the ability of the Company to continue". Only an actual denial is `negated`
  ("there is no substantial doubt", "did not raise", "has been alleviated", "no longer exists");
  "have not alleviated the substantial doubt" and "without financing, there is substantial
  doubt" are not. One that only imagines it ("could raise") is `hedged`.
"""

import re
from collections.abc import Iterator
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

_NUMBER = r"\d{1,3}(?:\.\d+)?"
_PCT = r"(?:\s*%|\s+percent\b|\s+per\s+cent\b)"
_APPROX = (
    r"(?:approximately|about|roughly|nearly|over|more\s+than|an\s+aggregate\s+of"
    r"|in\s+excess\s+of|at\s+least|greater\s+than)"
)
_PERCENT = rf"(?:{_APPROX}\s+)?{_NUMBER}{_PCT}(?:\s+or\s+(?:more|greater|higher))?"
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
_NUMBERS = re.compile(rf"({_NUMBER}){_PCT}")
_FLOOR = re.compile(
    r"\b(?:more\s+than|over|in\s+excess\s+of|at\s+least|greater\s+than|exceed\w*)\s+\d"
    r"|\bor\s+(?:more|greater|higher)\b",
    re.I,
)

# "a single end customer which represented 10% or more of our total net revenue ... is
# summarized below" defines who is listed; it is not a customer's share.
_THRESHOLD_DEFINITION = re.compile(
    rf"\b(?:which|that|who|whom)\s+(?:each\s+)?{_VERB}\s+(?:for\s+)?{_NUMBER}{_PCT}\s+or\s+"
    r"(?:more|greater|higher)\s*$",
    re.I,
)
_BUYER = r"(?:customers?|distributors?|resellers?|clients?|channel\s+partners?|oems?)"
_CUSTOMER = re.compile(rf"\b{_BUYER}\b|\bsales\s+to\b", re.I)
_COUNT = r"(?:two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|[2-9]|\d{2,})"
_GROUP = re.compile(
    rf"\b(?:top|largest)\s+(?:{_COUNT}\s+)?{_BUYER}\b"
    rf"|\b{_COUNT}\s+(?:largest\s+|top\s+)?{_BUYER}\b",
    re.I,
)
_EACH = re.compile(r"\beach\b", re.I)

# Where a share of revenue is: a region or country as the subject is not a customer.
_PLACES = frozenset(
    {
        "china", "chinese", "asia", "asian", "europe", "european", "emea", "apac", "americas",
        "america", "united", "states", "kingdom", "japan", "japanese", "taiwan", "korea",
        "korean", "india", "germany", "israel", "singapore", "malaysia", "vietnam", "thailand",
        "mexico", "canada", "africa", "australia", "brazil", "france", "finland", "sweden",
        "hong", "kong", "pacific", "middle", "east", "north", "south", "latin", "u", "s", "us",
        "uk", "eu", "prc", "ireland", "netherlands", "italy", "spain", "switzerland",
    }
)  # fmt: skip
_GEOGRAPHY = re.compile(
    r"\boutside\b|\bgeograph\w*|\bregions?\b|\bcountr(?:y|ies)\b|\blocated\s+in\b"
    r"|\bbased\s+in\b|\bshipped\s+to\b|\binternational\b|\bdomestic\b|\bforeign\b|\bworldwide\b"
    r"|\b(?:"
    + "|".join(sorted(_PLACES - {"u", "s", "us", "states", "east", "north", "south"}))
    + r")\b|\bU\.S\.|\bUnited\s+States\b",
    re.I,
)
_LABEL = re.compile(r"\b[Cc]ustomer\s+[A-Z0-9]\b")
_CAPITALISED = re.compile(r"\b[A-Z][A-Za-z&\-]*\b")
_NOT_NAMES = frozenset(
    {
        "during", "in", "for", "fiscal", "year", "years", "customers", "customer", "sales",
        "net", "revenue", "revenues", "our", "the", "total", "approximately", "about", "of",
        "from", "to", "and", "certain", "one", "two", "three", "four", "five", "ten", "largest",
        "top", "a", "an", "each", "as", "at", "by", "on", "with", "that", "which", "who", "these",
        "those", "company", "we", "us", "quarter", "quarters", "january", "february", "march",
        "april", "may", "june", "july", "august", "september", "october", "november",
        "december", "distributors", "distributor", "resellers", "clients", "oems", "oem",
        "since", "over", "under", "also", "however", "additionally", "if",
        "when", "where", "while", "although", "because", "individual", "single", "end",
    }
)  # fmt: skip

# A table row of the customer note: "Customer A<tab>26.6<tab>%<tab>15.4<tab>%" (the parse keeps a
# table's cells on one line, tab-separated, so a row has a tab). Only under a revenue heading,
# never a receivables one.
_ROW = re.compile(
    rf"^[ \t]*{_BUYER}\s+(?:[A-Z]|\d{{1,2}})\b[^\n\t]*\t[^\n]*$",
    re.I | re.M,
)
_REVENUE_WORD = re.compile(r"\b(?:revenues?|sales)\b", re.I)
_RECEIVABLES_WORD = re.compile(r"\breceivables?\b", re.I)
_ROW_CONTEXT = 1200
_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")

_NO_LARGE = re.compile(
    rf"\b(?:no|none\s+of\s+(?:our|the)|neither)\s+(?:single\s+|individual\s+|one\s+|other\s+)?"
    rf"{_BUYER}(?:\s+\w+){{0,3}}?\s+"
    r"(?:accounted\s+for|represent(?:ed|s)|exceed(?:ed|s)|comprised|constituted|contributed)\s+"
    rf"(?:{_APPROX}\s+)?(?P<n>{_NUMBER}){_PCT}",
    re.I,
)

_ABILITY = (
    r"(?:(?:our|its|the\s+company['\u2019]s|[A-Z][\w.&\- ]{0,40}?['\u2019]s)\s+ability"
    r"|the\s+ability\s+of\s+(?:the\s+company|us|[A-Z][\w.&\- ]{0,40}?))"
)
_GOING_CONCERN = re.compile(
    r"substantial\s+doubt\s+(?:about|regarding|as\s+to|concerning|over)\s+"
    rf"{_ABILITY}\s+to\s+continue\s+as\s+a\s+going\s+concern",
    re.I,
)
_ALLEVIATE = r"(?:alleviat|dispel|eliminat|remov|overcom)\w*"
# Immediately before the phrase: "there is no", "did not raise", "alleviated the" are denials;
# "have not alleviated the" is the opposite.
_AFFIRMED_BEFORE = re.compile(
    rf"(?:\bnot|\bnever|n['\u2019]t|\bfailed\s+to)\s+(?:\w+\s+){{0,2}}?{_ALLEVIATE}"
    r"(?:\s+(?:the|any))?\s+$",
    re.I,
)
_DENIED_BEFORE = re.compile(
    r"(?:\bno"
    r"|\b(?:did|do|does|would|will)\s+not\s+(?:raise|create|result\s+in|give\s+rise\s+to)"
    r"(?:\s+(?:any|a))?"
    rf"|\b{_ALLEVIATE}(?:\s+(?:the|any))?)\s+$",
    re.I,
)
_DENIED_AFTER = re.compile(
    r"\b(?:has|have|had)\s+been\s+(?:\w+\s+)?(?:alleviated|dispelled|eliminated|removed|overcome)\b"
    r"|\bwas\s+(?:\w+\s+)?(?:alleviated|dispelled|eliminated|overcome)\b"
    r"|\bno\s+longer\b|\b(?:does|do|did)\s+not\s+exist\b",
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
    """A sentence (or table row) that matches a pattern: `text[char_start:char_end] ==
    sentence`."""

    char_start: int
    char_end: int
    sentence: str


@dataclass(frozen=True)
class ConcentrationMatch(SentenceMatch):
    percents: tuple[Decimal, ...]  # as written, in order
    current: Decimal  # the current period's: the first, unless the years run oldest first
    floor: bool  # "more than 10%", "10% or more": a lower bound, not a value
    kind: Literal["customer", "top_customers"]


@dataclass(frozen=True)
class NoLargeCustomerMatch(SentenceMatch):
    threshold: Decimal  # "no customer accounted for more than <threshold>%"


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


def _is_region(subject: str) -> bool:
    """Whether the words that say whose share it is name a region or country and no customer."""
    if not _GEOGRAPHY.search(subject) or _LABEL.search(subject):
        return False
    names = [
        word
        for word in _CAPITALISED.findall(subject)
        if word.lower() not in _NOT_NAMES and word.lower() not in _PLACES
    ]
    return not names


def _current(percents: list[Decimal], years_in: str) -> Decimal:
    """The current period's percentage: the first, unless the years named run oldest first."""
    years = [int(each) for each in _YEAR.findall(years_in)]
    if len(percents) > 1 and len(years) >= 2 and years[0] < years[-1]:
        return percents[-1]
    return percents[0]


def customer_concentration(text: str) -> list[ConcentrationMatch]:
    """The sentences that say a customer "accounted for" N% of revenue, in text order, and the
    rows of a table that give customers' percentages ("Customer A  26.6 %  15.4 %"). A sentence
    must name a customer (or a distributor, reseller, OEM, "sales to ...") and not only a region
    or country; a row must follow a mention of revenue or sales with no mention of receivables
    after it. A sentence saying that no customer exceeded a threshold is not a share."""
    denied = [(m.start(), m.end()) for m in _NO_LARGE.finditer(text)]
    found: dict[tuple[int, int], ConcentrationMatch] = {}
    for row in _ROW.finditer(text):
        numbers = [Decimal(each) for each in _NUMBERS.findall(row.group())]
        if (
            numbers
            and not _RECEIVABLES_WORD.search(row.group())
            and _revenue_table(text, row.start())
        ):
            header = _header_years(text, row.start())
            found[(row.start(), row.end())] = ConcentrationMatch(
                row.start(),
                row.end(),
                row.group(),
                tuple(numbers),
                _current(numbers, header),
                bool(_FLOOR.search(row.group())),
                "customer",
            )
    for pattern in (_ACCOUNTED, _DERIVED):
        for match in pattern.finditer(text):
            span = sentence_span(text, match.start(), match.end())
            if span in found or any(span[0] <= start < span[1] for start, _ in denied):
                continue
            sentence = text[span[0] : span[1]]
            if not _CUSTOMER.search(sentence):
                continue
            if pattern is _ACCOUNTED:
                subject = text[span[0] : match.start()]
            else:
                subject = text[match.end() : span[1]]
            if _is_region(subject):
                continue
            listed = match.group("list")
            numbers = [Decimal(each) for each in _NUMBERS.findall(listed)]
            if not numbers or not all(Decimal(0) <= each <= Decimal(100) for each in numbers):
                continue
            if _THRESHOLD_DEFINITION.search(text[span[0] : match.end("list")]):
                continue  # "customers which represented 10% or more": the disclosure's threshold
            kind: Literal["customer", "top_customers"] = (
                "top_customers"
                if _GROUP.search(sentence) and not _EACH.search(sentence)
                else "customer"
            )
            found[span] = ConcentrationMatch(
                span[0],
                span[1],
                sentence,
                tuple(numbers),
                _current(numbers, text[match.end() : span[1]]),
                bool(_FLOOR.search(listed)),
                kind,
            )
    return [found[span] for span in sorted(found)]


def no_large_customer(text: str) -> list[NoLargeCustomerMatch]:
    """The sentences that say no customer accounted for more than a threshold of revenue."""
    found: dict[tuple[int, int], NoLargeCustomerMatch] = {}
    for match in _NO_LARGE.finditer(text):
        start, end = sentence_span(text, match.start(), match.end())
        found.setdefault(
            (start, end), NoLargeCustomerMatch(start, end, text[start:end], Decimal(match["n"]))
        )
    return [found[span] for span in sorted(found)]


def _revenue_table(text: str, position: int) -> bool:
    """Whether the rows at `position` follow a revenue (or sales) heading, not a receivables
    one: the last such word before them, within a page, is not "receivable"."""
    context = text[max(0, position - _ROW_CONTEXT) : position]
    revenue = [m.start() for m in _REVENUE_WORD.finditer(context)]
    receivables = [m.start() for m in _RECEIVABLES_WORD.finditer(context)]
    return bool(revenue) and (not receivables or max(revenue) > max(receivables))


def _header_years(text: str, position: int) -> str:
    """The nearest of the few lines above a table row that names two or more years."""
    for line in reversed(text[max(0, position - 600) : position].split("\n")[-5:]):
        if len(_YEAR.findall(line)) >= 2:
            return line
    return ""


def going_concern(text: str) -> list[GoingConcernMatch]:
    """The sentences that name substantial doubt about continuing as a going concern, in text
    order, each marked `negated` (the sentence actually denies it) or `hedged` (it says there
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
        negated = not _AFFIRMED_BEFORE.search(before) and bool(
            _DENIED_BEFORE.search(before) or _DENIED_AFTER.search(after)
        )
        hedged = bool(_HEDGE_BEFORE.search(before))
        found.append(GoingConcernMatch(start, end, text[start:end], negated, hedged))
    return found
