"""When an EDGAR filing becomes public, from its acceptanceDateTime (docs/decisions.md).

EDGAR disseminates a filing accepted on a business day up to 17:30 ET at once; one accepted
later (or on a weekend or federal holiday) is disseminated when EDGAR opens (06:00 ET) on the
next business day (EDGAR Filer Manual Vol. II §2.3.1, §3.2). Expected times are written out
in Eastern and UTC by hand, never computed the way the code does.
"""

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest

from atlas.sources import (
    EDGAR_CALENDAR_RANGE,
    EdgarCalendarRangeError,
    SecFiling,
    edgar_dissemination_time,
    filing_availability,
    is_edgar_business_day,
)

ET = ZoneInfo("America/New_York")


def et(*parts: int) -> datetime:
    return datetime(*parts, tzinfo=ET)  # pyright: ignore[reportArgumentType]


def utc(*parts: int) -> datetime:
    return datetime(*parts, tzinfo=UTC)  # pyright: ignore[reportArgumentType]


def test_acceptance_at_16_00_et_on_a_business_day_is_public_at_once() -> None:
    accepted = utc(2026, 8, 17, 20, 0)  # Monday 16:00 EDT

    assert edgar_dissemination_time(accepted, "10-K") == accepted


def test_the_window_closes_after_17_30_et() -> None:
    assert edgar_dissemination_time(et(2026, 8, 17, 17, 30), "10-Q") == et(2026, 8, 17, 17, 30)
    assert edgar_dissemination_time(et(2026, 8, 17, 17, 30, 1), "10-Q") == utc(2026, 8, 18, 10)


def test_acceptance_at_17_31_et_on_a_friday_is_public_monday_at_06_00_et() -> None:
    accepted = et(2026, 9, 25, 17, 31)  # Friday

    assert edgar_dissemination_time(accepted, "8-K") == et(2026, 9, 28, 6, 0)
    assert edgar_dissemination_time(accepted, "8-K") == utc(2026, 9, 28, 10, 0)


def test_acceptance_after_hours_on_a_holiday_eve_skips_the_holiday() -> None:
    # Wednesday before Thanksgiving (Thursday 2026-11-26): public Friday.
    assert edgar_dissemination_time(et(2026, 11, 25, 18, 5), "10-Q") == utc(2026, 11, 27, 11)
    # Thursday before Independence Day observed (Friday 2026-07-03): public Monday.
    assert edgar_dissemination_time(et(2026, 7, 2, 19, 0), "10-Q") == utc(2026, 7, 6, 10)
    # Tuesday 2025-12-23: EDGAR was closed 24-26 December 2025 (SEC announcement).
    assert edgar_dissemination_time(et(2025, 12, 23, 18, 0), "8-K") == utc(2025, 12, 29, 11)


def test_the_next_opening_is_06_00_eastern_across_a_dst_change() -> None:
    # Friday 2026-03-06 18:00 EST; clocks spring forward Sunday 2026-03-08.
    # Monday 06:00 is EDT, i.e. 10:00 UTC, not the 11:00 UTC a fixed offset would give.
    assert edgar_dissemination_time(utc(2026, 3, 6, 23, 0), "10-Q") == utc(2026, 3, 9, 10, 0)
    # Friday 2026-10-30 18:00 EDT; clocks fall back Sunday 2026-11-01. Monday 06:00 EST.
    assert edgar_dissemination_time(utc(2026, 10, 30, 22, 0), "10-Q") == utc(2026, 11, 2, 11, 0)


def test_weekend_holiday_and_pre_opening_acceptance_wait_for_the_opening() -> None:
    assert edgar_dissemination_time(et(2026, 9, 26, 12, 0), "10-K") == et(2026, 9, 28, 6, 0)
    assert edgar_dissemination_time(et(2026, 9, 7, 12, 0), "10-K") == et(2026, 9, 8, 6, 0)
    assert edgar_dissemination_time(et(2026, 9, 8, 5, 59), "10-K") == et(2026, 9, 8, 6, 0)


def test_ownership_forms_are_disseminated_until_22_00_et() -> None:
    accepted = et(2026, 9, 25, 20, 57)  # the fixture's Friday Form 4

    assert edgar_dissemination_time(accepted, "4") == accepted
    assert edgar_dissemination_time(accepted, "10-Q") == et(2026, 9, 28, 6, 0)


def test_the_holiday_table_is_explicit_and_fails_outside_its_range() -> None:
    first, last = EDGAR_CALENDAR_RANGE
    assert (first, last) == (date(2019, 1, 1), date(2027, 12, 31))
    assert not is_edgar_business_day(date(2026, 6, 19))  # Juneteenth
    assert not is_edgar_business_day(date(2025, 1, 9))  # closed for President Carter
    assert is_edgar_business_day(date(2021, 1, 20))  # Inauguration Day: EDGAR open
    with pytest.raises(EdgarCalendarRangeError, match="2027-12-31"):
        edgar_dissemination_time(et(2028, 3, 1, 12, 0), "10-K")
    with pytest.raises(EdgarCalendarRangeError):
        is_edgar_business_day(date(2018, 12, 31))
    # 2027-12-31 is a holiday (New Year's Day 2028 observed): the next opening is off the table.
    with pytest.raises(EdgarCalendarRangeError):
        edgar_dissemination_time(et(2027, 12, 30, 18, 0), "10-K")


def filing(accepted: datetime, form: str = "10-Q") -> SecFiling:
    return SecFiling(
        cik="0001633978",
        company_name="Lumentum Holdings Inc.",
        accession_number="0001628280-26-030777",
        form=form,
        filing_date=date(2026, 5, 6),
        report_date=date(2026, 3, 28),
        acceptance_datetime=accepted,
        primary_document="lite-20260328.htm",
    )


def test_a_filing_is_available_at_acceptance_or_at_its_dissemination() -> None:
    in_window = utc(2026, 5, 5, 20, 0)
    assert filing_availability(filing(in_window)) == (in_window, "sec_acceptance")
    # The fixture 10-Q: accepted Tuesday 18:03 EDT, filing date Wednesday 2026-05-06.
    assert filing_availability(filing(utc(2026, 5, 5, 22, 3, 3))) == (
        utc(2026, 5, 6, 10, 0),
        "sec_dissemination",
    )
