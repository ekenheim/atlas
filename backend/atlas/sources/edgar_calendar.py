"""When EDGAR makes an accepted filing public (docs/decisions.md, "EDGAR dissemination time").

EDGAR accepts filings each business day (Monday to Friday except federal holidays) from
06:00 to 22:00 ET (EDGAR Filer Manual Vol. II §2.3.1). A filing received after 17:30 ET gets
the next business day's filing date "and will not be disseminated until the next business
day"; Section 16 ownership forms, Form 144, Schedules 13D/13G and a few others are
disseminated until 22:00 ET (Vol. II §3.2). So, from `acceptanceDateTime`:

- accepted on a business day between 06:00 and the form's cutoff (inclusive): public at
  acceptance;
- otherwise: public when EDGAR opens (06:00 ET) on the next business day.

Times are converted with the America/New_York zone, so the opening is 06:00 EST or EDT as
the day requires.

The holiday table is explicit and maintained here. Each year is the federal holidays
(5 U.S.C. 6103, observed Friday/Monday when they fall on a weekend; checked against SEC's
published "EDGAR Calendar" for 2026) plus the extra closures SEC announced (executive-order
days off and national days of mourning). Inauguration Day is not a closure: EDGAR operated
normally on 20 January 2021 (SEC announcement). A date outside the table's range raises
`EdgarCalendarRangeError`: never guess. When SEC publishes the next year's calendar, add
that year, any extra closures, and move `EDGAR_CALENDAR_RANGE`.
"""

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

EASTERN = ZoneInfo("America/New_York")
EDGAR_OPENS = time(6, 0)
DISSEMINATION_CUTOFF = time(17, 30)
LATE_DISSEMINATION_CUTOFF = time(22, 0)

# Disseminated until 22:00 ET with a same-day filing date (Filer Manual Vol. II §3.2), as
# the current manual lists them. Not the old names "SC 13G" and "SC 13G/A": recorded
# indexes show those accepted after 17:30 in 2019-2023 with the next day's filing date.
LATE_DISSEMINATION_FORMS = frozenset(
    {
        "3",
        "3/A",
        "4",
        "4/A",
        "5",
        "5/A",
        "144",
        "144/A",
        "F-1MEF",
        "F-3MEF",
        "F-4MEF",
        "N-14MEF",
        "N-2MEF",
        "POS 462B",
        "S-11MEF",
        "S-1MEF",
        "S-3MEF",
        "S-4MEF",
        "S-BMEF",
        "SC 13D/A",
        "SCHEDULE 13D",
        "SCHEDULE 13D/A",
        "SCHEDULE 13G",
        "SCHEDULE 13G/A",
        "SC 14N",
        "SC 14N/A",
        "SC 14N-S",
    }
)

EDGAR_CALENDAR_RANGE = (date(2019, 1, 1), date(2027, 12, 31))

# Every weekday EDGAR is closed, within EDGAR_CALENDAR_RANGE.
EDGAR_HOLIDAYS: frozenset[date] = frozenset(
    date.fromisoformat(day)
    for day in """
    2019-01-01 2019-01-21 2019-02-18 2019-05-27 2019-07-04 2019-09-02 2019-10-14 2019-11-11
    2019-11-28 2019-12-25
    2019-12-24

    2020-01-01 2020-01-20 2020-02-17 2020-05-25 2020-07-03 2020-09-07 2020-10-12 2020-11-11
    2020-11-26 2020-12-25
    2020-12-24

    2021-01-01 2021-01-18 2021-02-15 2021-05-31 2021-06-18 2021-07-05 2021-09-06 2021-10-11
    2021-11-11 2021-11-25 2021-12-24 2021-12-31

    2022-01-17 2022-02-21 2022-05-30 2022-06-20 2022-07-04 2022-09-05 2022-10-10 2022-11-11
    2022-11-24 2022-12-26

    2023-01-02 2023-01-16 2023-02-20 2023-05-29 2023-06-19 2023-07-04 2023-09-04 2023-10-09
    2023-11-10 2023-11-23 2023-12-25

    2024-01-01 2024-01-15 2024-02-19 2024-05-27 2024-06-19 2024-07-04 2024-09-02 2024-10-14
    2024-11-11 2024-11-28 2024-12-25
    2024-12-24

    2025-01-01 2025-01-20 2025-02-17 2025-05-26 2025-06-19 2025-07-04 2025-09-01 2025-10-13
    2025-11-11 2025-11-27 2025-12-25
    2025-01-09 2025-12-24 2025-12-26

    2026-01-01 2026-01-19 2026-02-16 2026-05-25 2026-06-19 2026-07-03 2026-09-07 2026-10-12
    2026-11-11 2026-11-26 2026-12-25

    2027-01-01 2027-01-18 2027-02-15 2027-05-31 2027-06-18 2027-07-05 2027-09-06 2027-10-11
    2027-11-11 2027-11-25 2027-12-24 2027-12-31
    """.split()
)
# The second line of a year, where present, is SEC-announced extra closures: Christmas Eve
# by executive order (2019, 2020, 2024; 24 and 26 December 2025) and the national day of
# mourning for President Carter (9 January 2025). 2021-12-31 is New Year's Day 2022 observed,
# 2027-12-31 New Year's Day 2028 observed. 2027 is statutory only: SEC hasn't published it.


class EdgarCalendarRangeError(ValueError):
    """A date the EDGAR holiday table doesn't cover: extend the table, don't guess."""


def is_edgar_business_day(day: date) -> bool:
    """Whether EDGAR accepts and disseminates filings on this (Eastern) date."""
    first, last = EDGAR_CALENDAR_RANGE
    if not first <= day <= last:
        raise EdgarCalendarRangeError(
            f"{day} is outside the EDGAR holiday table ({first} to {last}); extend"
            " EDGAR_HOLIDAYS and EDGAR_CALENDAR_RANGE in atlas/sources/edgar_calendar.py"
        )
    return day.weekday() < 5 and day not in EDGAR_HOLIDAYS


def edgar_dissemination_time(accepted: datetime, form: str) -> datetime:
    """When a filing of `form` accepted at `accepted` became public on EDGAR, in UTC."""
    if accepted.tzinfo is None:
        raise ValueError(f"acceptance time without a time zone: {accepted!r}")
    local = accepted.astimezone(EASTERN)
    day = local.date()
    cutoff = LATE_DISSEMINATION_CUTOFF if form in LATE_DISSEMINATION_FORMS else DISSEMINATION_CUTOFF
    if is_edgar_business_day(day):
        if local.time() < EDGAR_OPENS:
            return _opening(day)
        if local.time() <= cutoff:
            return accepted.astimezone(UTC)
    day += timedelta(days=1)
    while not is_edgar_business_day(day):
        day += timedelta(days=1)
    return _opening(day)


def _opening(day: date) -> datetime:
    return datetime.combine(day, EDGAR_OPENS, tzinfo=EASTERN).astimezone(UTC)
