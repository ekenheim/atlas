"""The XBRL normalization gate (ticket 18): ingest, one worker pass, then `/api/v1`.

Seam: an `ingest` job run by the worker records the companyfacts Source Version and
normalizes it into `financial_observation`; figures are read through the HTTP API. Expected
values come from the recorded filings (the Q3 FY2026 10-Q's inline XBRL, the Q4 release's
EX-99.1) and the research note's worked examples, never recomputed the way the code does.
"""

import json
import re
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from atlas.jobs import JobQueue
from atlas.ledger.ingest import ingest_payload
from atlas.settings import Settings
from tests.harness import EDGAR_FIXTURES, REPO, Atlas

THEMES = REPO / "tests" / "fixtures" / "financials" / "themes.yaml"
LITE = EDGAR_FIXTURES / "lumentum"
LITE_FACTS = LITE / "data.sec.gov/api/xbrl/companyfacts/CIK0001633978.json"
LITE_ARCHIVES = LITE / "www.sec.gov/Archives/edgar/data/1633978"
LITE_10Q_HTML = LITE_ARCHIVES / "000162828026030777/lite-20260328.htm"
LITE_EX991 = LITE_ARCHIVES / "000162828026055726/lite_ex991xq4fy26.htm"
LITE_10Q = "0001628280-26-030777"
LITE_10K = "0001628280-26-057358"
NOW = "2026-09-29T00:00:00Z"


class FinancialsAtlas(Atlas):
    """The harness on a Lumentum + Nokia universe, without Hindsight (no retains)."""

    def settings(self) -> Settings:
        return super().settings().model_copy(update={"hindsight_url": None})

    def ingest_job(self, company: str, key: str | None = None) -> dict[str, Any]:
        enqueued = JobQueue(self.engine).enqueue(
            "ingest", key or company, ingest_payload(company, None, None)
        )
        self.worker_pass()
        job = self.get(f"/api/v1/jobs/{enqueued.job.id}")
        assert job["status"] == "succeeded", job["failures"]
        return job

    def figures(self, company: str, as_of: str = NOW, **params: Any) -> list[dict[str, Any]]:
        company_id = self.company(company)["id"]
        return self.get(f"/api/v1/companies/{company_id}/financials", as_of=as_of, **params)[
            "figures"
        ]

    def figure(
        self, company: str, metric: str, start: str | None, end: str, as_of: str = NOW
    ) -> dict[str, Any] | None:
        found = [
            f
            for f in self.figures(company, as_of, metric=metric)
            if f["period_start"] == start and f["period_end"] == end
        ]
        return found[0] if found else None

    def observations(self, company: str, as_of: str = NOW, **filters: Any) -> list[dict[str, Any]]:
        company_id = self.company(company)["id"]
        items: list[dict[str, Any]] = []
        while True:
            page = self.get(
                f"/api/v1/companies/{company_id}/financial-observations",
                as_of=as_of,
                limit=500,
                offset=len(items),
                **filters,
            )
            items += page["items"]
            if len(items) >= page["total"]:
                return items


@pytest.fixture
def atlas(database_url: str, tmp_path: Path) -> Iterator[FinancialsAtlas]:
    atlas = FinancialsAtlas(database_url, tmp_path, "http://127.0.0.1:1", themes_config=THEMES)
    yield atlas
    atlas.engine.dispose()


def inline_xbrl(html: str) -> dict[tuple[str, str | None, str], tuple[Decimal, str]]:
    """{(concept, start, end): (value, unit)} of the non-dimensional numeric facts."""
    contexts: dict[str, tuple[str | None, str]] = {}
    for context_id, body in re.findall(
        r'<xbrli:context id="([^"]+)">(.*?)</xbrli:context>', html, re.S
    ):
        if "xbrli:segment" in body:
            continue
        start = re.search(r"<xbrli:startDate>([^<]+)", body)
        end = re.search(r"<xbrli:(?:endDate|instant)>([^<]+)", body)
        assert end is not None
        contexts[context_id] = (start[1] if start else None, end[1])
    units = {"usd": "USD", "shares": "shares", "usdPerShare": "USD/shares"}
    facts: dict[tuple[str, str | None, str], tuple[Decimal, str]] = {}
    for attributes, shown in re.findall(r"<ix:nonFraction([^>]*)>([^<]*)", html):
        attrs = dict(re.findall(r'([\w:]+)="([^"]*)"', attributes))
        if attrs.get("contextRef") not in contexts or not re.fullmatch(r"[\d,.]+", shown):
            continue
        value = Decimal(shown.replace(",", "")).scaleb(int(attrs.get("scale", "0")))
        if attrs.get("sign") == "-":
            value = -value
        facts[(attrs["name"], *contexts[attrs["contextRef"]])] = (value, units[attrs["unitRef"]])
    return facts


def test_ingest_normalizes_companyfacts_once_and_audits_it(atlas: FinancialsAtlas) -> None:
    facts = json.loads(LITE_FACTS.read_bytes())["facts"]
    fact_count = sum(
        len(unit_facts)
        for concepts in facts.values()
        for concept in concepts.values()
        for unit_facts in concept["units"].values()
    )

    first = atlas.ingest_job("lumentum", "first")
    second = atlas.ingest_job("lumentum", "second")

    normalization = first["artifacts"]["financial_normalization"]
    assert normalization["facts_read"] == fact_count
    assert normalization["observations_created"] == fact_count  # one fact per filing and key
    assert "financial_normalization" not in second["artifacts"]  # unchanged: already done
    with atlas.engine.connect() as connection:
        events = connection.execute(
            text(
                "SELECT entity_id FROM audit_event WHERE action = 'financial_normalization.created'"
            )
        ).all()
        stored = connection.execute(text("SELECT count(*) FROM financial_observation")).scalar()
    assert [e.entity_id for e in events] == [normalization["id"]]
    assert stored == fact_count
    verify = atlas.cli("audit", "verify")
    assert verify.returncode == 0, verify.stderr


def test_observations_reconcile_to_the_filed_10q(atlas: FinancialsAtlas) -> None:
    atlas.ingest_job("lumentum")
    filed = inline_xbrl(LITE_10Q_HTML.read_text(encoding="utf-8"))

    # As of the 10-Q's dissemination, before the 10-K, its facts are the as-of values.
    from_10q = [
        o
        for o in atlas.observations("lumentum", "2026-05-06T12:00:00Z")
        if o["accession"] == LITE_10Q and o["taxonomy"] == "us-gaap"
    ]

    # The recorded 10-Q is truncated (see its manifest): facts past the cut can't be checked.
    reconciled = [
        o
        for o in from_10q
        if (f"us-gaap:{o['concept']}", o["period_start"], o["period_end"]) in filed
    ]
    assert len(reconciled) >= 25
    for observation in reconciled:
        concept = f"us-gaap:{observation['concept']}"
        value, unit = filed[(concept, observation["period_start"], observation["period_end"])]
        assert Decimal(observation["value"]) == value, concept
        assert observation["unit"] == unit, concept
    for observation in from_10q:
        assert observation["available_at"] == "2026-05-06T10:00:00Z"
        assert observation["available_at_basis"] == "sec_dissemination"
        assert observation["form"] == "10-Q"
    concepts = {o["concept"] for o in reconciled}
    assert {
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "LongTermDebtCurrent",
        "LongTermDebtNoncurrent",
        "WeightedAverageNumberOfDilutedSharesOutstanding",
    } <= concepts


def test_revenue_reconciles_to_the_q4_release(atlas: FinancialsAtlas) -> None:
    atlas.ingest_job("lumentum")
    release = re.sub(r"<[^>]+>|&#160;", " ", LITE_EX991.read_text(encoding="utf-8"))
    # The release's statement of operations columns: Q4 FY26, Q4 FY25, FY26, FY25.
    assert re.search(
        r"Net\s+revenue\s+\$\s+1,006\.3\s+\$\s+480\.7\s+\$\s+3,014\.0\s+\$\s+1,645\.0", release
    )

    q4 = atlas.figure("lumentum", "revenue", "2026-03-29", "2026-06-27")
    q4_prior = atlas.figure("lumentum", "revenue", "2025-03-30", "2025-06-28")
    fy = atlas.figure("lumentum", "revenue", "2025-06-29", "2026-06-27")
    fy_prior = atlas.figure("lumentum", "revenue", "2024-06-30", "2025-06-28")

    assert q4 is not None and q4_prior is not None and fy is not None and fy_prior is not None
    assert Decimal(q4["value"]) == Decimal("1006300000")
    assert Decimal(q4_prior["value"]) == Decimal("480700000")
    assert Decimal(fy["value"]) == Decimal("3014000000")
    assert Decimal(fy_prior["value"]) == Decimal("1645000000")
    assert (q4["derived"], q4["period_type"], q4["period_days"]) == (True, "quarter", 91)
    assert [s["accession"] for s in q4["sources"]] == [LITE_10K, LITE_10Q]
    assert q4["available_at"] == "2026-08-17T20:03:17Z"
    assert (fy["derived"], fy["period_type"], fy["period_days"]) == (False, "year", 364)
    assert (fy["unit"], fy["currency"], fy["fx_basis"]) == ("USD", "USD", None)

    # Before the 10-K is accepted there is no FY2026 figure: the release has no XBRL.
    assert (
        atlas.figure("lumentum", "revenue", "2025-06-29", "2026-06-27", "2026-08-12T00:00:00Z")
        is None
    )
    assert (
        atlas.figure("lumentum", "revenue", "2026-03-29", "2026-06-27", "2026-08-17T20:00:00Z")
        is None
    )


def test_capex_debt_and_diluted_shares_as_of_the_10k(atlas: FinancialsAtlas) -> None:
    atlas.ingest_job("lumentum")

    def value(metric: str, start: str | None, end: str) -> Decimal:
        figure = atlas.figure("lumentum", metric, start, end)
        assert figure is not None, metric
        return Decimal(figure["value"])

    # The research note's FY2026 10-K values (§2).
    assert value("capex", "2025-06-29", "2026-06-27") == Decimal("451300000")
    assert value("total_debt", None, "2026-06-27") == Decimal("1637400000")
    assert value("debt_current", None, "2026-06-27") == Decimal("1596900000")
    assert value("debt_noncurrent", None, "2026-06-27") == Decimal("40500000")
    assert value("diluted_shares", "2025-06-29", "2026-06-27") == Decimal("74600000")
    assert value("shares_outstanding", None, "2026-06-27") == Decimal("88600000")
    # The Q3 10-Q's nine-month capex (inline XBRL: 284.5).
    assert value("capex", "2025-06-29", "2026-03-28") == Decimal("284500000")


def test_every_figure_exposes_its_source(atlas: FinancialsAtlas) -> None:
    atlas.ingest_job("lumentum")
    atlas.ingest_job("nokia")

    figures = atlas.figures("lumentum") + atlas.figures("nokia")

    assert len(figures) > 50
    for figure in figures:
        assert figure["sources"], figure
        assert len(figure["sources"]) == (2 if figure["derived"] else 1)
        for source in figure["sources"]:
            for field in ("accession", "concept", "taxonomy", "period_end", "unit", "available_at"):
                assert source[field], (field, figure)
            assert source["available_at"] <= figure["available_at"]
            assert source["unit"] == figure["unit"]


def test_nokia_fy2023_revenue_restatement(atlas: FinancialsAtlas) -> None:
    atlas.ingest_job("nokia")

    before = atlas.figure("nokia", "revenue", "2023-01-01", "2023-12-31", "2025-03-13T17:00:00Z")
    after = atlas.figure("nokia", "revenue", "2023-01-01", "2023-12-31", "2025-03-13T17:30:00Z")

    assert before is not None and after is not None
    assert (Decimal(before["value"]), before["sources"][0]["accession"]) == (
        Decimal("22258000000"),
        "0000924613-24-000013",
    )
    assert (Decimal(after["value"]), after["sources"][0]["accession"]) == (
        Decimal("21138000000"),
        "0000924613-25-000008",
    )
    for figure in (before, after):
        assert (figure["unit"], figure["currency"], figure["fx_basis"]) == ("EUR", "EUR", None)
        assert figure["sources"][0]["taxonomy"] == "ifrs-full"
    restated = after["sources"][0]
    assert restated["linkage"] == "restates"
    assert restated["available_at"] == "2025-03-13T17:24:32Z"

    history = atlas.get(f"/api/v1/financial-observations/{restated['id']}")["history"]
    assert [(Decimal(o["value"]), o["linkage"]) for o in history] == [
        (Decimal("22258000000"), "first"),
        (Decimal("21138000000"), "restates"),
    ]
    assert history[1]["previous_observation_id"] == history[0]["id"]
    assert history[0]["available_at_basis"] == "sec_filing_date_eod"
    assert history[0]["available_at"] == "2024-03-01T04:59:59Z"  # 2024-02-29 23:59:59 EST


def test_currencies_are_never_mixed(atlas: FinancialsAtlas) -> None:
    atlas.ingest_job("lumentum")
    atlas.ingest_job("nokia")

    nokia = atlas.figures("nokia")
    lumentum = atlas.figures("lumentum", metric=["revenue", "capex", "eps_diluted"])

    assert {f["currency"] for f in nokia} == {"EUR"}
    assert {(f["unit"], f["currency"]) for f in lumentum} == {
        ("USD", "USD"),
        ("USD/shares", "USD"),
    }
    assert all(f["fx_basis"] is None for f in nokia + lumentum)
    for figure in nokia + lumentum:
        assert {s["unit"] for s in figure["sources"]} == {figure["unit"]}


def test_observations_are_insert_only(atlas: FinancialsAtlas) -> None:
    atlas.ingest_job("nokia")

    with pytest.raises(DBAPIError, match="immutable"), atlas.engine.begin() as connection:
        connection.execute(text("UPDATE financial_observation SET value = 0"))
    with pytest.raises(DBAPIError, match="immutable"), atlas.engine.begin() as connection:
        connection.execute(text("DELETE FROM financial_observation"))


def test_financials_errors(atlas: FinancialsAtlas) -> None:
    atlas.ingest_job("nokia")
    company_id = atlas.company("nokia")["id"]

    unknown_metric = atlas.api.get(
        f"/api/v1/companies/{company_id}/financials", params={"metric": "ebitda"}
    )
    missing = atlas.api.get("/api/v1/companies/00000000-0000-0000-0000-000000000000/financials")
    naive = atlas.api.get(
        f"/api/v1/companies/{company_id}/financials", params={"as_of": "2025-01-01T00:00:00"}
    )
    no_observation = atlas.api.get(
        "/api/v1/financial-observations/00000000-0000-0000-0000-000000000000"
    )

    assert unknown_metric.status_code == 422
    assert unknown_metric.json()["error"]["code"] == "invalid_request"
    assert missing.status_code == 404
    assert naive.status_code == 422
    assert no_observation.status_code == 404
