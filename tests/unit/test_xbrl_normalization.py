"""The XBRL as-of selector and metric layer (ticket 18), on the companyfacts fixtures.

Worked examples from docs/research/xbrl-normalization.md §4.5 (branch
research/xbrl-normalization): expected values come from that note, the recorded Lumentum
filings (the FY2026 Q4 release's EX-99.1, the Q3 10-Q) and the fixtures, never recomputed.
"""

import json
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from atlas.financials import (
    CurrencyMismatch,
    MetricValue,
    Observation,
    PeriodKey,
    derive_difference,
    load_metric_catalog,
    metric_values,
    normalize,
    parse_companyfacts,
    select_as_of,
)
from atlas.sources.edgar import parse_submissions

REPO = Path(__file__).parents[2]
EDGAR = REPO / "tests" / "fixtures" / "edgar"
CATALOG = load_metric_catalog(REPO / "configs" / "financials" / "metrics.yaml")
FETCHED = datetime(2026, 9, 28, 20, 50, tzinfo=UTC)  # when the companyfacts was recorded

LITE_10K = "0001628280-26-057358"  # FY2026, accepted 2026-08-17 16:03:17 ET
LITE_10Q = "0001628280-26-030777"  # Q3 FY2026, accepted 2026-05-05 18:03:03 ET (held)
NOKIA_20F_2024 = "0000924613-24-000013"  # FY2023, filed 2024-02-29
NOKIA_20F_2025 = "0000924613-25-000008"  # FY2024, accepted 2025-03-13 17:24:32Z
NOKIA_20F_2026 = "0001628280-26-015034"  # FY2025, filed 2026-03-05

INCLUDING = "RevenueFromContractWithCustomerIncludingAssessedTax"
NOKIA_REVENUE = PeriodKey(
    "ifrs-full", "RevenueFromContractsWithCustomers", "EUR", date(2023, 1, 1), date(2023, 12, 31)
)


def at(timestamp: str) -> datetime:
    return datetime.fromisoformat(timestamp)


def companyfacts(company: str, cik: str) -> bytes:
    return (EDGAR / company / f"data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json").read_bytes()


def observations(company: str, cik: str, content: bytes | None = None) -> list[Observation]:
    submissions = (EDGAR / company / f"data.sec.gov/submissions/CIK{cik}.json").read_bytes()
    return normalize(
        parse_companyfacts(content or companyfacts(company, cik)),
        parse_submissions(submissions),
        source_version_id=uuid.uuid4(),
        snapshot_available_at=FETCHED,
    )


@pytest.fixture(scope="module")
def lumentum() -> list[Observation]:
    return observations("lumentum", "0001633978")


@pytest.fixture(scope="module")
def nokia() -> list[Observation]:
    return observations("nokia", "0000924613")


def figures(
    selected: dict[PeriodKey, Observation], metric: str, start: date | None, end: date
) -> list[MetricValue]:
    return [
        v
        for v in metric_values(selected, CATALOG, [metric])
        if v.period_start == start and v.period_end == end
    ]


def by_id(history: list[Observation]) -> dict[uuid.UUID, Observation]:
    return {o.id: o for o in history}


# --- availability: the filing's, never the fetch time ---


def test_a_held_10q_is_invisible_until_edgar_disseminates_it(lumentum: list[Observation]):
    q3 = PeriodKey("us-gaap", INCLUDING, "USD", date(2025, 12, 28), date(2026, 3, 28))

    assert q3 not in select_as_of(lumentum, at("2026-05-05T23:00:00+00:00"))
    selected = select_as_of(lumentum, at("2026-05-06T12:00:00+00:00"))[q3]
    assert selected.value == Decimal("808400000")
    assert selected.accession == LITE_10Q
    # Accepted 18:03 ET, after the 17:30 cutoff: public at 06:00 ET the next business day.
    assert selected.accepted_at == at("2026-05-05T22:03:03+00:00")
    assert selected.available_at == at("2026-05-06T10:00:00+00:00")
    assert selected.available_at_basis == "sec_dissemination"


def test_an_accession_missing_from_submissions_is_available_at_its_filing_dates_end(
    lumentum: list[Observation],
):
    inventory = PeriodKey("us-gaap", "InventoryNet", "USD", None, date(2018, 6, 30))
    q1_10q = next(
        o for o in lumentum if o.key == inventory and o.accession == "0001628280-18-013240"
    )

    assert q1_10q.filed == date(2018, 11, 1)
    assert q1_10q.available_at == at("2018-11-01T23:59:59-04:00")
    assert q1_10q.available_at_basis == "sec_filing_date_eod"
    assert q1_10q.accepted_at is None


# --- worked examples (research note §4.5) ---


def test_lumentum_q4_fy2026_revenue_is_fy_minus_9m(lumentum: list[Observation]):
    selected = select_as_of(lumentum, at("2026-08-17T20:10:00+00:00"))

    (q4,) = figures(selected, "revenue", date(2026, 3, 29), date(2026, 6, 27))
    # The Q4 FY2026 earnings release (EX-99.1, 8-K 0001628280-26-055726): "Net revenue $ 1,006.3".
    assert q4.value == Decimal("1006300000")
    assert q4.derived
    assert q4.unit == "USD"
    assert q4.currency == "USD"
    assert q4.concept == INCLUDING
    assert [(s.accession, s.value) for s in q4.sources] == [
        (LITE_10K, Decimal("3014000000")),
        (LITE_10Q, Decimal("2007700000")),
    ]
    assert q4.available_at == at("2026-08-17T20:03:17+00:00")  # the 10-K's acceptance
    assert q4.flags == ("derived",)


def test_fy2026_revenue_is_invisible_until_the_10k(lumentum: list[Observation]):
    # The release (2026-08-11) carries no XBRL; the 10-K was accepted 2026-08-17 20:03:17Z.
    for cutoff in ("2026-08-12T00:00:00+00:00", "2026-08-17T20:03:16+00:00"):
        selected = select_as_of(lumentum, at(cutoff))
        assert figures(selected, "revenue", date(2025, 6, 29), date(2026, 6, 27)) == []
        assert figures(selected, "revenue", date(2026, 3, 29), date(2026, 6, 27)) == []


def test_q4_fy2025_is_derived_across_revenue_tags(lumentum: list[Observation]):
    selected = select_as_of(lumentum, at("2026-09-29T00:00:00+00:00"))

    (q4,) = figures(selected, "revenue", date(2025, 3, 30), date(2025, 6, 28))
    # The same release: Q4 FY2025 net revenue "$ 480.7".
    assert q4.value == Decimal("480700000")
    assert {s.concept for s in q4.sources} == {
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        INCLUDING,
    }
    assert q4.concept is None


def test_tag_precedence_within_one_filing(lumentum: list[Observation]):
    selected = select_as_of(lumentum, at("2026-09-29T00:00:00+00:00"))

    (fy,) = figures(selected, "revenue", date(2025, 6, 29), date(2026, 6, 27))
    # The FY2026 10-K tags Including and Excluding with the same 3,014.0M: Including wins.
    assert fy.value == Decimal("3014000000")
    assert fy.concept == INCLUDING
    assert fy.flags == ()
    assert not fy.derived


def test_nokia_fy2023_revenue_restatement(nokia: list[Observation]):
    before = select_as_of(nokia, at("2025-03-13T17:00:00+00:00"))[NOKIA_REVENUE]
    after = select_as_of(nokia, at("2025-03-13T17:30:00+00:00"))[NOKIA_REVENUE]

    assert (before.value, before.accession) == (Decimal("22258000000"), NOKIA_20F_2024)
    assert before.available_at_basis == "sec_filing_date_eod"
    assert (after.value, after.accession) == (Decimal("21138000000"), NOKIA_20F_2025)
    assert after.available_at == at("2025-03-13T17:24:32+00:00")
    assert after.available_at_basis == "sec_acceptance"
    assert after.linkage == "restates"
    assert after.previous_observation_id == before.id
    assert after.suspect_reasons == ()  # -5%, same sign, a recent period
    assert before.linkage == "first"
    assert before.currency == after.currency == "EUR"


def test_a_key_restated_twice_keeps_every_value(nokia: list[Observation]):
    key = NOKIA_REVENUE._replace(concept="ProfitLossFromOperatingActivities")
    history = sorted((o for o in nokia if o.key == key), key=lambda o: o.order)

    assert [(o.value, o.accession, o.linkage) for o in history] == [
        (Decimal("1688000000"), NOKIA_20F_2024, "first"),
        (Decimal("1661000000"), NOKIA_20F_2025, "restates"),
        (Decimal("1733000000"), NOKIA_20F_2026, "restates"),
    ]
    assert [o.previous_observation_id for o in history] == [None, history[0].id, history[1].id]
    assert select_as_of(nokia, at("2026-09-29T00:00:00+00:00"))[key].value == Decimal("1733000000")


def test_inventory_restatement_links_reaffirmations_and_ignores_frame(
    lumentum: list[Observation],
):
    key = PeriodKey("us-gaap", "InventoryNet", "USD", None, date(2018, 6, 30))

    early = select_as_of(lumentum, at("2019-01-01T00:00:00+00:00"))[key]
    late = select_as_of(lumentum, at("2019-09-01T00:00:00+00:00"))[key]

    assert (early.value, early.accession, early.linkage) == (
        Decimal("153600000"),
        "0001628280-18-013240",
        "reaffirms",
    )
    assert early.frame is None  # SEC's frame sits on the latest filing, not the as-of one
    assert (late.value, late.accession, late.linkage) == (
        Decimal("174100000"),
        "0001633978-19-000069",
        "restates",
    )
    assert late.frame == "CY2018Q2I"
    assert late.suspect_reasons == ()
    history = by_id([o for o in lumentum if o.key == key])
    assert late.previous_observation_id is not None
    assert history[late.previous_observation_id].accession == "0001633978-19-000030"


def test_an_eps_mis_tag_is_suspect_but_still_selected(lumentum: list[Observation]):
    key = PeriodKey(
        "us-gaap", "EarningsPerShareDiluted", "USD/shares", date(2015, 6, 28), date(2015, 9, 26)
    )

    selected = select_as_of(lumentum, at("2018-03-01T00:00:00+00:00"))[key]

    # The 10-Q of 2018-02-06 put the six-month FY2018 EPS (3.29) on a 2015 quarter.
    assert selected.value == Decimal("3.29")
    assert selected.accession == "0001628280-18-001086"
    assert selected.linkage == "restates"
    assert set(selected.suspect_reasons) == {"large_change", "old_period"}
    corrected = select_as_of(lumentum, at("2018-04-01T00:00:00+00:00"))[key]
    assert (corrected.value, corrected.form) == (Decimal("0"), "10-K/A")


def test_fy_and_fp_describe_the_filing_not_the_period(lumentum: list[Observation]):
    key = PeriodKey(
        "us-gaap",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "USD",
        date(2023, 7, 2),
        date(2024, 6, 29),
    )

    selected = select_as_of(lumentum, at("2026-09-29T00:00:00+00:00"))[key]

    assert (selected.value, selected.accession) == (Decimal("1359200000"), LITE_10K)
    assert (selected.fiscal_year, selected.fiscal_period) == (2026, "FY")  # FY2024's value
    assert selected.linkage == "reaffirms"


# --- 52/53-week calendars ---


def test_a_53_week_year_and_its_14_week_quarter(lumentum: list[Observation]):
    selected = select_as_of(lumentum, at("2022-01-01T00:00:00+00:00"))
    gross = {
        (v.period_start, v.period_end): v
        for v in metric_values(selected, CATALOG, ["gross_profit"])
    }

    fy2021 = gross[(date(2020, 6, 28), date(2021, 7, 3))]  # 371 days
    q3 = gross[(date(2020, 12, 27), date(2021, 4, 3))]  # 98 days
    q4 = gross[(date(2021, 4, 4), date(2021, 7, 3))]
    assert fy2021.value == Decimal("783100000")
    assert q3.value == Decimal("185000000")
    # The 10-K reports Q4 FY2021 itself, so it isn't derived, and it equals FY - 9M.
    assert (q4.value, q4.derived) == (Decimal("162800000"), False)
    assert gross[(date(2020, 6, 28), date(2021, 4, 3))].value == Decimal("620300000")


# --- currencies and units ---


def test_values_in_different_currencies_are_never_combined():
    facts = {
        "cik": 924613,
        "entityName": "NOKIA CORP",
        "facts": {
            "ifrs-full": {
                "Revenue": {
                    "units": {
                        "EUR": [
                            {"start": "2023-01-01", "end": "2023-12-31", "val": 1000,
                             "accn": NOKIA_20F_2024, "fy": 2023, "fp": "FY", "form": "20-F",
                             "filed": "2024-02-29"},
                        ],
                        "USD": [
                            {"start": "2023-01-01", "end": "2023-09-30", "val": 700,
                             "accn": NOKIA_20F_2024, "fy": 2023, "fp": "FY", "form": "20-F",
                             "filed": "2024-02-29"},
                        ],
                    }
                }
            }
        },
    }  # fmt: skip
    selected = select_as_of(
        observations("nokia", "0000924613", json.dumps(facts).encode()),
        at("2026-01-01T00:00:00+00:00"),
    )

    revenue = metric_values(selected, CATALOG, ["revenue"])

    assert [(v.unit, v.derived) for v in revenue] == [("EUR", False), ("USD", False)]
    year, nine_months = sorted(revenue, key=lambda v: v.unit)
    with pytest.raises(CurrencyMismatch):
        derive_difference("revenue", year, nine_months)


def test_share_counts_and_per_share_values_are_never_derived(lumentum: list[Observation]):
    selected = select_as_of(lumentum, at("2026-09-29T00:00:00+00:00"))

    for metric in ("diluted_shares", "eps_diluted"):
        assert not any(v.derived for v in metric_values(selected, CATALOG, [metric]))
    (fy,) = figures(selected, "diluted_shares", date(2025, 6, 29), date(2026, 6, 27))
    assert (fy.value, fy.unit, fy.currency) == (Decimal("74600000"), "shares", None)


# --- later snapshots ---


def test_a_later_snapshot_stores_only_what_changed(nokia: list[Observation]):
    submissions = parse_submissions(
        (EDGAR / "nokia/data.sec.gov/submissions/CIK0000924613.json").read_bytes()
    )
    content = json.loads(companyfacts("nokia", "0000924613"))
    revised_at = at("2026-10-01T12:00:00+00:00")

    assert (
        normalize(
            parse_companyfacts(json.dumps(content).encode()),
            submissions,
            source_version_id=uuid.uuid4(),
            snapshot_available_at=revised_at,
            existing=nokia,
        )
        == []
    )

    inventories = content["facts"]["ifrs-full"]["Inventories"]["units"]["EUR"]
    inventories[0]["val"] = 2210000000  # the same accession, a different value
    (revised,) = normalize(
        parse_companyfacts(json.dumps(content).encode()),
        submissions,
        source_version_id=uuid.uuid4(),
        snapshot_available_at=revised_at,
        existing=nokia,
    )

    assert revised.accession == NOKIA_20F_2026
    assert (revised.available_at, revised.available_at_basis) == (revised_at, "observed_revision")
    assert revised.linkage == "restates"
    assert revised.previous_observation_id is not None
    assert by_id(nokia)[revised.previous_observation_id].value == Decimal("2209000000")
