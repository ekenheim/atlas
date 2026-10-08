"""A company's fiscal calendar, from the fiscal years its filings closed (R2-02).

`fiscal_year_end` is the (month, day) its annual reports end on, read from the XBRL
observations of its 10-K, 10-K/A, 20-F and 40-F filings that cover a full year
(`fiscal_period = 'FY'`). Filers on a 52/53-week year end on a Saturday near the month's end
(Lumentum: 2024-06-29, 2025-06-28, 2023-07-01), so every period end is first rounded to the
nearest month end; the most common wins. Nothing here is guessed: a company with no such
observation has no fiscal year end, and the caller treats it as a calendar-year filer and says
so (`atlas.facts.periods`).
"""

import calendar
import uuid
from collections import Counter
from datetime import date

from sqlalchemy import Connection, text

from atlas.facts.periods import FiscalYearEnd

ANNUAL_FORMS = ("10-K", "10-K/A", "20-F", "40-F")
# A period end on one of the first days of a month closes the previous month's 52/53-week year.
MONTH_START_DAYS = 7


def month_end(day: date) -> FiscalYearEnd:
    """The (month, last day) of the month a fiscal year ending on `day` belongs to."""
    year, month = (day.year, day.month) if day.day > MONTH_START_DAYS else _previous(day)
    return month, calendar.monthrange(year, month)[1]


def _previous(day: date) -> tuple[int, int]:
    return (day.year - 1, 12) if day.month == 1 else (day.year, day.month - 1)


def fiscal_year_end(connection: Connection, company_id: uuid.UUID) -> FiscalYearEnd | None:
    """The modal fiscal year end of the company, or None without annual observations. A tie
    goes to the later year end."""
    rows = connection.execute(
        text(
            "SELECT period_end, count(*) AS observations FROM financial_observation"
            " WHERE company_id = :company AND fiscal_period = 'FY' AND form = ANY(:forms)"
            " GROUP BY period_end"
        ),
        {"company": company_id, "forms": list(ANNUAL_FORMS)},
    ).all()
    if not rows:
        return None
    counts: Counter[FiscalYearEnd] = Counter()
    latest: dict[FiscalYearEnd, date] = {}
    for period_end, observations in rows:
        end = month_end(period_end)
        counts[end] += observations
        latest[end] = max(latest.get(end, period_end), period_end)
    return max(counts, key=lambda end: (counts[end], latest[end]))
