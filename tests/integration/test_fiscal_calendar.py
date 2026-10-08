"""A company's fiscal year end, read from the annual reports' XBRL observations (R2-02).

Seam: `atlas.financials.calendar.fiscal_year_end` over `financial_observation` rows. The rows
are seeded directly (the figures are not the point): the period ends are the real ones of the
52/53-week filers the rule is for (Lumentum's June Saturdays) and of a calendar-year filer.
"""

import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from sqlalchemy import text

from atlas.archive import open_archive
from atlas.audit import Actor
from atlas.financials.calendar import fiscal_year_end
from atlas.ledger.service import SourceLedger
from atlas.sources import FetchedDocument, HttpValidators, SourceCandidate
from tests.harness import Atlas

NOW = datetime(2026, 9, 20, tzinfo=UTC)


@pytest.fixture
def atlas(database_url: str, tmp_path: Path) -> Iterator[Atlas]:
    atlas = Atlas(database_url, tmp_path, "http://127.0.0.1:1")
    seeded = atlas.cli("companies", "seed")
    assert seeded.returncode == 0, seeded.stderr
    yield atlas
    atlas.engine.dispose()


def version_of(atlas: Atlas, slug: str) -> uuid.UUID:
    """A Source Version of the company (a companyfacts document) for the rows to point at."""
    url = f"https://data.sec.gov/api/xbrl/companyfacts/{slug}.json"
    settings = atlas.settings()
    ledger = SourceLedger(atlas.engine, open_archive(settings), Actor.from_settings(settings))
    fetch = ledger.record(
        FetchedDocument(
            candidate=SourceCandidate(
                provider_id="sec_edgar",
                kind="sec_companyfacts",
                url=url,
                title=f"XBRL companyfacts for {slug}",
                discovered_at=NOW,
                available_at=NOW,
                available_at_basis="observed_discovery",
                language="en",
            ),
            url=url,
            fetched_at=NOW,
            not_modified=False,
            content=b"{}",
            media_type="application/json",
            validators=HttpValidators(),
            attempts=(),
        ),
        company_id=uuid.UUID(atlas.company(slug)["id"]),
    )
    return fetch.source_version_id


def observe(
    atlas: Atlas,
    slug: str,
    version: uuid.UUID,
    period_end: date,
    *,
    form: str = "10-K",
    fiscal_period: str | None = "FY",
) -> None:
    """One revenue observation of a filing, as the normalizer stores them."""
    with atlas.engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO financial_observation (id, company_id, cik, source_version_id,"
                " accession, form, filed, fiscal_year, fiscal_period, taxonomy, concept, unit,"
                " currency, period_end, value, available_at, available_at_basis, linkage)"
                " VALUES (gen_random_uuid(), :company, '0000000001', :version, :accession, :form,"
                " :filed, :year, :fp, 'us-gaap', 'Revenues', 'USD', 'USD', :end, 1000, :now,"
                " 'sec_filing_date_eod', 'first')"
            ),
            {
                "company": atlas.company(slug)["id"],
                "version": version,
                "accession": f"0000000001-26-{uuid.uuid4().int % 10**6:06d}",
                "form": form,
                "filed": period_end,
                "year": period_end.year,
                "fp": fiscal_period,
                "end": period_end,
                "now": NOW,
            },
        )


def year_end(atlas: Atlas, slug: str) -> tuple[int, int] | None:
    with atlas.engine.connect() as connection:
        return fiscal_year_end(connection, uuid.UUID(atlas.company(slug)["id"]))


def test_the_fiscal_year_end_is_the_modal_fy_period_end_normalised_to_a_month_end(
    atlas: Atlas,
) -> None:
    lumentum = version_of(atlas, "lumentum")
    # Lumentum's 52/53-week years end on the Saturday nearest June 30: the 28th, the 29th and
    # the 1st of July all mean a June 30 year end.
    for end in (date(2024, 6, 29), date(2025, 6, 28), date(2023, 7, 1)):
        observe(atlas, "lumentum", lumentum, end)
    # What is not a fiscal year's close is not read: a quarter, a form that is not an annual
    # report, and another company's.
    observe(atlas, "lumentum", lumentum, date(2025, 3, 29), form="10-Q", fiscal_period="Q3")
    observe(atlas, "lumentum", lumentum, date(2025, 12, 27), form="8-K")
    observe(atlas, "lumentum", lumentum, date(2025, 9, 27), fiscal_period="Q1")

    assert year_end(atlas, "lumentum") == (6, 30)
    # No annual observation, no fiscal year end: the caller treats it as a calendar year.
    assert year_end(atlas, "coherent") is None


def test_a_calendar_year_filer_on_a_52_53_week_year_ends_in_december(atlas: Atlas) -> None:
    axt = version_of(atlas, "axt")
    for end in (date(2023, 12, 31), date(2025, 1, 3), date(2023, 12, 30)):
        observe(atlas, "axt", axt, end)
    for end in (date(2024, 12, 31),):
        observe(atlas, "axt", axt, end, form="10-K/A")

    assert year_end(atlas, "axt") == (12, 31)


def test_the_most_common_year_end_wins_and_the_later_one_breaks_a_tie(atlas: Atlas) -> None:
    ciena = version_of(atlas, "ciena")
    # A change of fiscal year: two October closes, then two in January; the later wins the tie.
    for end in (date(2022, 10, 29), date(2023, 10, 28), date(2025, 1, 31), date(2026, 1, 31)):
        observe(atlas, "ciena", ciena, end)
    assert year_end(atlas, "ciena") == (1, 31)
    observe(atlas, "ciena", ciena, date(2024, 11, 2))  # a third October-ish close
    assert year_end(atlas, "ciena") == (10, 31)
