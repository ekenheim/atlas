"""Periods resolved in code from the document's date and the company's fiscal calendar (no
database): the fiscal quarter of a day, the readings of each relative phrase, and the two
refusals (`period_misresolved`, `period_other_document`). Expected values are the calendar
facts: Coherent's fiscal year ends June 30, Marvell's January 31, AXT's December 31."""

# The quarter labels the module writes use an en dash, which the tests spell out as written.
# ruff: noqa: RUF001

from datetime import date

import pytest

from atlas.assertions import InvalidAssertion
from atlas.facts.periods import (
    FiscalYearEnd,
    check_period,
    fiscal_quarter,
    resolve,
    resolved_text,
)

JUNE: FiscalYearEnd = (6, 30)


def refused(
    quote: str,
    period: str | None,
    day: date,
    fye: FiscalYearEnd | None = JUNE,
    statement: str = "the company expects growth",
) -> InvalidAssertion:
    with pytest.raises(InvalidAssertion) as raised:
        check_period(quote, statement, period, day, fye)
    return raised.value


def labels(quote: str, day: date, fye: FiscalYearEnd | None = JUNE) -> list[list[str]]:
    return [[c.label for c in each.candidates] for each in resolve(quote, day, fye)]


@pytest.mark.parametrize(
    ("day", "fye", "expected"),
    [
        (date(2025, 11, 5), (6, 30), (2026, 2)),  # Coherent, the first call of its fiscal 2026
        (date(2026, 2, 4), (6, 30), (2026, 3)),
        (date(2026, 5, 6), (6, 30), (2026, 4)),
        (date(2026, 10, 6), (1, 31), (2027, 3)),  # Marvell
        (date(2026, 2, 19), (12, 31), (2026, 1)),  # AXT
        (date(2026, 2, 19), None, (2026, 1)),  # no calendar known: the calendar year
        (date(2026, 7, 1), (6, 30), (2027, 1)),  # the day after a fiscal year ends
        (date(2026, 6, 30), (6, 30), (2026, 4)),  # its last day
    ],
)
def test_fiscal_quarters_follow_the_company_s_year_end(
    day: date, fye: FiscalYearEnd | None, expected: tuple[int, int]
) -> None:
    assert fiscal_quarter(day, fye) == expected


def test_each_relative_phrase_resolves_to_its_candidates() -> None:
    feb = date(2026, 2, 4)
    # A calendar year is the document's year only, whatever the fiscal year.
    assert labels("on track by the end of this calendar year", feb) == [["calendar 2026"]]
    # "This year" on a June filer is either: the calendar year and the fiscal year it is in.
    assert labels("we expect this year to be strong", feb) == [["calendar 2026", "FY2026"]]
    assert labels("we expect this year to be strong", feb, (12, 31)) == [["calendar 2026"]]
    assert labels("we expect next year to be strong", feb) == [["calendar 2027", "FY2027"]]
    assert labels("next calendar year", feb) == [["calendar 2027"]]
    assert labels("this fiscal year", feb) == [["FY2026"]]
    assert labels("our next fiscal year", feb) == [["FY2027"]]
    # In a fiscal year's first quarter, the year that has just closed is a reading of "this"
    # (an annual report speaks of it so); the calendar filer's "this year" stays one reading.
    august = date(2026, 8, 14)
    assert labels("the current fiscal year", august) == [["FY2027", "FY2026"]]
    assert labels("this year", august) == [["calendar 2026", "FY2027", "FY2026"]]
    assert labels("this year", feb, (12, 31)) == [["calendar 2026"]]
    # Quarter phrases: the one the phrase says first, then the one before it (a call speaks
    # from the quarter it reports) and the one after.
    assert labels("in the current quarter", feb)[0] == [
        "Q3 FY2026 (Jan–Mar 2026)",
        "Q2 FY2026 (Oct–Dec 2025)",
        "Q4 FY2026 (Apr–Jun 2026)",
    ]
    assert labels("next quarter", feb)[0][0] == "Q4 FY2026 (Apr–Jun 2026)"
    assert labels("last quarter", feb)[0] == [
        "Q2 FY2026 (Oct–Dec 2025)",
        "Q1 FY2026 (Jul–Sep 2025)",
        "Q3 FY2026 (Jan–Mar 2026)",
    ]
    assert labels("the previous quarter", date(2025, 8, 5))[0][0] == "Q4 FY2025 (Apr–Jun 2025)"
    # A fiscal year that spans two calendar years names both in a quarter's months.
    assert labels("next quarter", date(2026, 10, 6), (1, 31))[0][0] == (
        "Q4 FY2027 (Nov 2026–Jan 2027)"
    )
    # Halves.
    assert labels("the first half of next year", feb) == [
        ["first half of calendar 2027", "first half of FY2027"]
    ]
    assert labels("in the second half", feb, (12, 31)) == [["second half of calendar 2026"]]
    # Absolute fiscal years are read too, for the years the quote itself names.
    [absolute] = resolve("during fiscal 26 and FY2027", feb, JUNE)[:1]
    assert (absolute.kind, absolute.candidates[0].year) == ("absolute", 2026)
    # No phrase, no resolution.
    assert resolve("we shipped 800G transceivers", feb, JUNE) == []
    assert resolved_text([], feb, JUNE) is None


def test_the_resolution_is_written_for_the_editor() -> None:
    day = date(2026, 2, 4)
    resolutions = resolve(
        "by the fourth quarter of this calendar year, and the current quarter", day, JUNE
    )
    assert resolved_text(resolutions, day, JUNE) == (
        "this calendar year = calendar 2026; the current quarter = Q3 FY2026 (Jan–Mar 2026);"
        " document dated 2026-02-04 (fiscal year ends 06-30)"
    )
    assert resolved_text(resolve("this year", day, None), day, None) == (
        "this year = calendar 2026;"
        " document dated 2026-02-04 (fiscal year end unknown, calendar year assumed)"
    )
    # A fiscal year written out is not a relative phrase: nothing to resolve.
    assert resolved_text(resolve("in fiscal 2026", day, JUNE), day, JUNE) is None


def test_a_year_contradicting_the_resolution_is_refused_naming_it() -> None:
    quote = "we are on track to double by the fourth quarter of this calendar year"
    feb = date(2026, 2, 4)
    error = refused(quote, "by Q4 calendar 2025", feb)
    assert error.code == "period_misresolved"
    assert "'this calendar year' on a document of 2026-02-04 is calendar 2026, not 2025" in (
        error.message
    )
    check_period(quote, "Coherent will double", "by Q4 calendar 2026", feb, JUNE)
    # The year only in the statement is refused too.
    assert (
        refused(quote, "by Q4", feb, statement="Coherent will double by the end of 2025").code
        == "period_misresolved"
    )
    # A quarter label whose year no reading of "the current quarter" gives.
    error = refused("revenue grew in the current quarter", "Q1 FY2024", feb)
    assert error.code == "period_misresolved"
    assert "Q3 FY2026 (Jan–Mar 2026)" in error.message


def test_a_year_in_the_quote_or_the_document_s_own_year_is_never_judged() -> None:
    check_period(
        "demand last quarter exceeded supply",
        "demand exceeded supply",
        "last quarter (call of November 2025)",
        date(2025, 11, 5),
        JUNE,
    )
    # The quote names the year, whatever else it says.
    check_period("this year, and 2029 for the new fab", "x", "through 2029", date(2026, 2, 4), JUNE)
    # No relative phrase in the quote: the year is not judged here (the quote may be silent).
    check_period("we shipped 800G units", "units shipped", "FY2019", date(2026, 2, 4), JUNE)
    check_period(
        "we expect to grow again next year",
        "growth next year",
        "Q3 FY2025 (fiscal quarter ended November 2024)",
        date(2024, 12, 3),
        (2, 28),
    )


def test_a_quarter_s_calendar_months_are_a_reading_of_the_phrase() -> None:
    feb = date(2026, 2, 4)
    quote = "demand last quarter exceeded supply"
    check_period(quote, "demand exceeded supply", "quarter ended December 31, 2025", feb, JUNE)
    check_period(quote, "demand exceeded supply", "Q2 FY2026 (Oct–Dec 2025)", feb, JUNE)
    check_period(
        quote, "demand exceeded supply in the December 2025 quarter", "last quarter", feb, JUNE
    )
    check_period(
        "next quarter will be up",
        "growth",
        "quarter ending January 2027",
        date(2026, 10, 6),
        (1, 31),
    )


def test_an_ambiguous_this_year_allows_the_fiscal_and_the_calendar_reading() -> None:
    quote = "we expect record revenue this year"
    on_june_filer = date(2025, 11, 5)  # calendar 2025, fiscal 2026
    check_period(quote, "record revenue", "calendar 2025", on_june_filer, JUNE)
    check_period(quote, "record revenue", "FY2026", on_june_filer, JUNE)
    assert refused(quote, "FY2027", on_june_filer).code == "period_misresolved"
    # A calendar filer has one reading.
    assert refused(quote, "FY2026", on_june_filer, (12, 31)).code == "period_misresolved"
    # Not knowing the fiscal calendar assumes the calendar's.
    assert refused(quote, "FY2026", on_june_filer, None).code == "period_misresolved"


def test_a_quarter_label_that_is_a_document_label_or_in_the_quote_is_not_judged() -> None:
    feb = date(2026, 2, 4)
    # "Q2 2026 call" names the call, not the quarter the phrase means.
    check_period(
        "we delivered in the current quarter",
        "delivered",
        "current quarter (Q2 2026 call)",
        feb,
        JUNE,
    )
    # The quote's own label is the quote's.
    check_period(
        "In Q1 we shipped more, up from this quarter a year ago", "x", "Q1 2026", feb, JUNE
    )
    check_period(
        "the first quarter was strong; next quarter will be too", "x", "Q1 FY2026", feb, JUNE
    )


def test_a_period_naming_another_document_s_date_is_refused() -> None:
    error = refused("we filed our annual report", "10-K filed 2026-08-17", date(2023, 5, 9), None)
    assert error.code == "period_other_document"
    assert "2026-08-17" in error.message
    assert "2023-05-09" in error.message
    # A date the quote writes is the quote's own.
    check_period(
        "as of February 4, 2025 we had 40 customers",
        "40 customers",
        "as of February 4, 2025",
        date(2023, 5, 9),
        None,
    )
    check_period(
        "the 10-K filed February 4, 2025 said so",
        "said so",
        "10-K filed February 4, 2025",
        date(2023, 5, 9),
        None,
    )
    error = refused("we shipped more", "Q3 2025 call, October 30, 2025", date(2024, 10, 31), None)
    assert error.code == "period_other_document"
    assert "2025-10-30" in error.message or "October 30, 2025" in error.message
    # The document's own month, or a date within 45 days of it, is the document.
    check_period("we shipped", "x", "last quarter (call of November 2025)", date(2025, 11, 5), JUNE)
    check_period("we shipped", "x", "8-K filed 2025-10-20", date(2025, 11, 5), JUNE)
    # A date not following a document word is not a document's: "as of" alone is a basis.
    check_period("x", "x", "as of March 31, 2019", date(2026, 2, 4), JUNE)
