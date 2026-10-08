"""Periods resolved in code from the document's date and the company's fiscal calendar
(pilot-review round 2, task R2-02).

A Fact keeps a relative phrase of its quote ("this calendar year", "the current quarter") in
its `period`, as `reader.v3` asks, because a blanket "the year must be in the quote" rule
refuses right Facts. What the phrase means depends on the day the document was said or filed
and, for a quarter or a fiscal year, on the company's fiscal calendar, and a model that guesses
it gets it wrong ("the fourth quarter of this calendar year" on a February 2026 call recorded as
2025; "the current quarter" on a November call labelled the wrong fiscal quarter). Code knows
both, so it resolves the phrase, and:

- `check_period` refuses a Fact whose period (or statement) names a year or a fiscal quarter
  that no reading of the quote's relative phrases gives (`period_misresolved`), and one whose
  period dates a document other than the one quoted (`period_other_document`);
- `resolved_text` is what the Editor and the judges are shown beside the period, so they stop
  guessing too.

Pure functions, no database: the caller supplies the document's date and the fiscal year end
(`atlas.financials.calendar.fiscal_year_end`; None means calendar, and says so in the basis).
Rules in `docs/decisions.md`, "Periods resolved from the document's date".
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date

from atlas.assertions import InvalidAssertion

# (month, day) of the fiscal year's last day: fiscal year N ends on (N, month, day).
FiscalYearEnd = tuple[int, int]
CALENDAR_YEAR_END: FiscalYearEnd = (12, 31)

_FLAGS = re.IGNORECASE
_THIS = r"(?:this|the current)"

# Each phrase, matched in the QUOTE; the kind is what `resolve` switches on. Absolute fiscal
# years ("fiscal 2026", "FY26") are matched too, only to say which years the quote itself names.
RELATIVE_PHRASES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("calendar_year", re.compile(rf"\b{_THIS} calendar year\b", _FLAGS)),
    (
        "year",
        re.compile(rf"\b(?:{_THIS} year|end of (?:this|the) year|year-end|year end)\b", _FLAGS),
    ),
    ("next_calendar_year", re.compile(r"\bnext calendar year\b", _FLAGS)),
    ("next_year", re.compile(r"\b(?:next year|the coming year)\b", _FLAGS)),
    ("fiscal_year", re.compile(rf"\b{_THIS} fiscal year\b", _FLAGS)),
    ("next_fiscal_year", re.compile(r"\bnext fiscal year\b", _FLAGS)),
    ("quarter", re.compile(rf"\b{_THIS} quarter\b", _FLAGS)),
    ("next_quarter", re.compile(r"\bnext quarter\b", _FLAGS)),
    ("last_quarter", re.compile(r"\b(?:last|the prior|the previous) quarter\b", _FLAGS)),
    (
        "half",
        re.compile(
            r"\b(?P<which>first|second) half"
            r"(?: of (?P<when>this|the|next)(?: (?P<basis>calendar|fiscal))? year)?\b",
            _FLAGS,
        ),
    ),
    (
        "absolute",
        re.compile(r"\bfiscal (?:20)?\d\d\b|\bFY ?'?\d\d(?:\d\d)?\b", _FLAGS),
    ),
)
_QUARTER_KINDS = ("quarter", "next_quarter", "last_quarter")

# A date a period gives for another document, and what marks it as one.
DOCUMENT_REFERENCES = ("filed", "call", "10-K", "10-Q", "8-K", "filing", "conference")
OTHER_DOCUMENT_DAYS = 45

_MONTHS = {
    name.lower(): number
    for number in range(1, 13)
    for name in (calendar.month_name[number], calendar.month_abbr[number])
}
_MONTH = "|".join(sorted((re.escape(n) for n in _MONTHS), key=len, reverse=True))
_DATE = re.compile(
    rf"(?P<iso>\d{{4}}-\d{{2}}-\d{{2}})"
    rf"|\b(?P<m1>{_MONTH})\.? (?P<d>\d{{1,2}})(?:st|nd|rd|th)?,? (?P<y1>\d{{4}})"
    rf"|\b(?P<m2>{_MONTH})\.?,? (?P<y2>\d{{4}})",
    _FLAGS,
)
_REFERENCED_DATE = re.compile(
    r"\b(?:" + "|".join(re.escape(each) for each in DOCUMENT_REFERENCES) + r")\b"
    r"(?P<gap>[^\d]{0,25}?)(?P<date>" + _DATE.pattern + ")",
    _FLAGS,
)
_YEAR = re.compile(r"(?<![\d.,$])(?:19|20)\d\d(?!\d)")
_ORDINALS = {"first": 1, "second": 2, "third": 3, "fourth": 4}
_QUARTER_IN_QUOTE = re.compile(
    r"\bQ([1-4])\b|\b(first|second|third|fourth) quarter\b|\b([1-4])(?:st|nd|rd|th) quarter\b",
    _FLAGS,
)
_QUARTER_LABEL = re.compile(
    r"\bQ(?P<q>[1-4])\b[ ,]*(?:(?P<pre>FY|fiscal|calendar|CY)\s*)?"
    r"(?P<year>\d{4}|'\d\d|(?<=FY)\d\d)(?!\d)",
    _FLAGS,
)
_DOCUMENT_LABEL = re.compile(r".{0,12}?\b(?:call|8-K|10-Q|10-K)\b", re.IGNORECASE)


@dataclass(frozen=True)
class Candidate:
    """One reading of a phrase: a year (a fiscal year's number for a fiscal reading), the
    quarter if it is a quarter, whether it is the calendar reading, and the other calendar
    years a quarter's months fall in."""

    label: str
    year: int
    quarter: int | None
    calendar: bool
    also_years: tuple[int, ...] = ()

    @property
    def years(self) -> frozenset[int]:
        return frozenset((self.year, *self.also_years))


@dataclass(frozen=True)
class Resolution:
    phrase: str
    kind: str
    candidates: list[Candidate]


def _end(fye: FiscalYearEnd | None) -> FiscalYearEnd:
    return CALENDAR_YEAR_END if fye is None else fye


def fiscal_quarter(day: date, fye: FiscalYearEnd | None) -> tuple[int, int]:
    """The fiscal year and quarter (1-4) of `day`; a fiscal year N ends on (N, month, day) of
    `fye`; None means the calendar year."""
    month, last = _end(fye)
    past = (day.month, day.day) > (month, last)
    fiscal_year = day.year + 1 if past else day.year
    shifted = day.month + 1 if day.month == month and day.day > last else day.month
    return fiscal_year, ((shifted - month - 1) % 12) // 3 + 1


def _step(fiscal_year: int, quarter: int, by: int) -> tuple[int, int]:
    index = fiscal_year * 4 + quarter - 1 + by
    return index // 4, index % 4 + 1


def _months(fiscal_year: int, quarter: int, fye: FiscalYearEnd | None) -> tuple[int, int, int, int]:
    """(first month's year, month, last month's year, month) of a fiscal quarter."""
    month, _ = _end(fye)
    last = fiscal_year * 12 + month - 1 - 3 * (4 - quarter)
    first = last - 2
    return first // 12, first % 12 + 1, last // 12, last % 12 + 1


def _quarter(fiscal_year: int, quarter: int, fye: FiscalYearEnd | None) -> Candidate:
    y1, m1, y2, m2 = _months(fiscal_year, quarter, fye)
    first, last = calendar.month_abbr[m1], calendar.month_abbr[m2]
    dash = "\N{EN DASH}"
    span = f"{first}{dash}{last} {y2}" if y1 == y2 else f"{first} {y1}{dash}{last} {y2}"
    return Candidate(
        label=f"Q{quarter} FY{fiscal_year} ({span})",
        year=fiscal_year,
        quarter=quarter,
        calendar=fye is None or fye == CALENDAR_YEAR_END,
        also_years=tuple(sorted({y1, y2} - {fiscal_year})),
    )


def _calendar_year(year: int) -> Candidate:
    return Candidate(f"calendar {year}", year, None, True)


def _fiscal_year(year: int, fye: FiscalYearEnd | None) -> Candidate:
    return Candidate(f"FY{year}", year, None, fye is None or fye == CALENDAR_YEAR_END)


def _years(
    year: int, fiscal_year: int, fye: FiscalYearEnd | None, basis: str | None
) -> list[Candidate]:
    """The calendar year, and the fiscal year when it is another reading, as the phrase's
    basis allows (`calendar`, `fiscal`, or None for either)."""
    readings: list[Candidate] = []
    if basis != "fiscal":
        readings.append(_calendar_year(year))
    if basis != "calendar" and fye is not None and fye != CALENDAR_YEAR_END:
        readings.append(_fiscal_year(fiscal_year, fye))
    elif basis == "fiscal":
        readings.append(_calendar_year(year))
    return readings


def _candidates(
    kind: str, match: re.Match[str], day: date, fye: FiscalYearEnd | None
) -> list[Candidate]:
    fiscal_year, quarter = fiscal_quarter(day, fye)
    year = day.year
    if kind == "calendar_year":
        return [_calendar_year(year)]
    # In a fiscal year's first quarter an annual report or a year-end call speaks of the year
    # that has just closed as "this" one: its reading comes second.
    just_closed = [_fiscal_year(fiscal_year - 1, fye)] if quarter == 1 else []
    if kind == "year":
        readings = _years(year, fiscal_year, fye, None)
        return readings + (just_closed if len(readings) > 1 else [])
    if kind == "next_calendar_year":
        return [_calendar_year(year + 1)]
    if kind == "next_year":
        return _years(year + 1, fiscal_year + 1, fye, None)
    if kind == "fiscal_year":
        return _years(year, fiscal_year, fye, "fiscal") + just_closed
    if kind == "next_fiscal_year":
        return _years(year + 1, fiscal_year + 1, fye, "fiscal")
    if kind in _QUARTER_KINDS:
        # The phrase's own quarter first, then the ones either side: a call is made after the
        # quarter it reports, and speaks from either.
        offset = {"quarter": 0, "next_quarter": 1, "last_quarter": -1}[kind]
        return [_quarter(*_step(fiscal_year, quarter, offset + each), fye) for each in (0, -1, 1)]
    if kind == "half":
        half = match.group("which").lower()
        when = (match.group("when") or "").lower()
        basis = (match.group("basis") or "").lower() or None
        shifts = [1] if when == "next" else [0]
        # Said after the half's midpoint ("the second half of the calendar year" in
        # November), a half unqualified by "this" may be the coming one.
        if when in ("", "the") and day.month > (3 if half == "first" else 9):
            shifts.append(1)
        return [
            Candidate(f"{half} half of {each.label}", each.year, None, each.calendar)
            for shift in shifts
            for each in _years(year + shift, fiscal_year + shift, fye, basis)
        ]
    # absolute: "fiscal 2026", "FY26": the fiscal year named, which ends in its own year.
    digits = re.sub(r"\D", "", match.group(0))
    named = int(digits) if len(digits) == 4 else 2000 + int(digits[-2:])
    return [Candidate(f"FY{named}", named, None, fye is None or fye == CALENDAR_YEAR_END)]


def resolve(quote: str, document_date: date, fye: FiscalYearEnd | None) -> list[Resolution]:
    """The relative phrases of `quote` in order of appearance, each with the readings it can
    have on a document of this date (the first is the plain one), phrases that overlap
    resolved once (the longer)."""
    found: list[tuple[int, int, str, re.Match[str]]] = []
    for kind, pattern in RELATIVE_PHRASES:
        found.extend((m.start(), m.end(), kind, m) for m in pattern.finditer(quote))
    found.sort(key=lambda each: (each[0], -(each[1] - each[0])))
    resolutions: list[Resolution] = []
    taken = 0
    for start, end, kind, match in found:
        if start < taken:
            continue
        taken = end
        resolutions.append(
            Resolution(
                phrase=" ".join(match.group(0).split()),
                kind=kind,
                candidates=_candidates(kind, match, document_date, fye),
            )
        )
    return resolutions


def _relative(resolutions: list[Resolution]) -> list[Resolution]:
    """The relative ones (not "fiscal 2026"), one for each distinct phrase."""
    seen: set[str] = set()
    relative: list[Resolution] = []
    for each in resolutions:
        if each.kind != "absolute" and each.phrase.lower() not in seen:
            seen.add(each.phrase.lower())
            relative.append(each)
    return relative


def _readings(resolution: Resolution) -> str:
    if resolution.kind in _QUARTER_KINDS:
        return resolution.candidates[0].label
    return " or ".join(each.label for each in resolution.candidates)


def resolved_text(
    resolutions: list[Resolution], document_date: date, fye: FiscalYearEnd | None
) -> str | None:
    """What the relative phrases mean on this document, in words for the Editor and the
    judges; None when the quote has none."""
    relative = _relative(resolutions)
    if not relative:
        return None
    parts = [f"{each.phrase} = {_readings(each)}" for each in relative]
    ends = (
        f"fiscal year ends {fye[0]:02d}-{fye[1]:02d}"
        if fye is not None
        else "fiscal year end unknown, calendar year assumed"
    )
    parts.append(f"document dated {document_date.isoformat()} ({ends})")
    return "; ".join(parts)


def _years_in(text: str) -> list[int]:
    return list(dict.fromkeys(int(each) for each in _YEAR.findall(text)))


def _quote_quarters(quote: str) -> set[int]:
    numbers: set[int] = set()
    for match in _QUARTER_IN_QUOTE.finditer(quote):
        if match.group(1):
            numbers.add(int(match.group(1)))
        elif match.group(2):
            numbers.add(_ORDINALS[match.group(2).lower()])
        else:
            numbers.add(int(match.group(3)))
    return numbers


def _label_year(text: str) -> int:
    digits = re.sub(r"\D", "", text)
    return int(digits) if len(digits) == 4 else 2000 + int(digits)


def _misresolved(
    quote: str,
    statement: str,
    period: str | None,
    document_date: date,
    resolutions: list[Resolution],
) -> None:
    relative = _relative(resolutions)
    if not relative:
        return
    words = f"{period or ''}\n{statement}"
    readings = "; ".join(
        f"'{each.phrase}' on a document of {document_date.isoformat()} is {_readings(each)}"
        for each in relative
    )
    allowed = {document_date.year, *_years_in(quote)}
    # Every calendar year a reading gives: a quarter reading's months name their calendar
    # years too (Q2 FY2026 is Oct-Dec 2025, so 2025 is a reading of 'last quarter' on 2026-02-04).
    allowed |= {y for each in resolutions for c in each.candidates for y in c.years}
    for year in _years_in(words):
        if year not in allowed:
            raise InvalidAssertion("period_misresolved", f"{readings}, not {year}")
    quarters = [each for each in relative if each.kind in _QUARTER_KINDS]
    if not quarters:
        return
    in_quote = _quote_quarters(quote)
    readings = "; ".join(
        f"'{each.phrase}' on a document of {document_date.isoformat()} is"
        f" {' or '.join(c.label for c in each.candidates)}"
        for each in quarters
    )
    for match in _QUARTER_LABEL.finditer(words):
        number, year = int(match.group("q")), _label_year(match.group("year"))
        if number in in_quote or _DOCUMENT_LABEL.match(words, match.end()):
            continue
        if any(
            c.quarter == number and year in c.years for each in quarters for c in each.candidates
        ):
            continue
        raise InvalidAssertion(
            "period_misresolved", f"{readings}, not {' '.join(match.group(0).split())}"
        )


def _date_of(match: re.Match[str]) -> tuple[date, date, bool]:
    """(first day, last day, whether a day was written) of a matched date: a month and year
    alone span the month."""
    try:
        if match.group("iso"):
            day = date.fromisoformat(match.group("iso"))
            return day, day, True
        if match.group("m1"):
            day = date(
                int(match.group("y1")), _MONTHS[match.group("m1").lower()], int(match.group("d"))
            )
            return day, day, True
        year, month = int(match.group("y2")), _MONTHS[match.group("m2").lower()]
    except ValueError:
        # Not a date ("2026-13-45"); nothing to judge.
        return date.min, date.min, True
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1]), False


def _other_document(quote: str, period: str | None, document_date: date) -> None:
    if not period:
        return
    written = [_date_of(each) for each in _DATE.finditer(quote)]
    for match in _REFERENCED_DATE.finditer(period):
        first, last, exact = _date_of(match)
        if first == date.min:
            continue
        if any(
            (first, last) == (w_first, w_last)
            or (not exact and (w_first.year, w_first.month) == (first.year, first.month))
            for w_first, w_last, _ in written
        ):
            continue
        apart = (
            0
            if first <= document_date <= last
            else min(abs((document_date - first).days), abs((document_date - last).days))
        )
        if apart > OTHER_DOCUMENT_DAYS:
            raise InvalidAssertion(
                "period_other_document",
                f"the period dates a document {match.group('date')} but this document is dated"
                f" {document_date.isoformat()} ({apart} days apart): a period names the quoted"
                " document, or a date its quote writes",
            )


def check_period(
    quote: str,
    statement: str,
    period: str | None,
    document_date: date,
    fye: FiscalYearEnd | None,
) -> None:
    """Raises `InvalidAssertion`: `period_misresolved` when the period or the statement names a
    year (or a fiscal quarter) that no reading of the quote's relative phrases gives, or
    `period_other_document` when the period dates a document that is not this one. Each message
    names the phrase, the document's date and what the phrase means."""
    _misresolved(quote, statement, period, document_date, resolve(quote, document_date, fye))
    _other_document(quote, period, document_date)
