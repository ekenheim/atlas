"""The mechanical bear checks (Chokepoint Watch ticket W4): `GET /api/v1/companies/{id}/bear-checks`
and the Atlas MCP tool `bear_checks`.

Seams: the worker ingests the recorded EDGAR fixtures (XBRL companyfacts, filings) for Lumentum
and Coherent; hand-built filings are recorded through the source ledger; everything is read
through `/api/v1` and `/mcp`. No model or network is involved. Expected values are the fixtures'
own, worked out by hand from the companyfacts (the comments say how), never read from the code.
"""

import json
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from atlas.archive import open_archive
from atlas.audit import Actor
from atlas.cli import seed_companies
from atlas.jobs import JobQueue
from atlas.ledger.ingest import ingest_payload
from atlas.ledger.service import SourceLedger
from atlas.settings import Settings
from atlas.sources import FetchedDocument, HttpValidators, SourceCandidate
from atlas.sources.adapter import SecFiling
from tests.harness import REPO, Atlas

THEMES = REPO / "tests" / "fixtures" / "financials" / "themes.yaml"
NOW = "2026-09-29T00:00:00Z"
KEYS = [
    "dilution",
    "shelf_or_atm",
    "gaap_gross_margin",
    "customer_concentration",
    "going_concern",
    "net_cash",
]
FILLER = "The company designs and sells optical components to customers in several markets."


class BearAtlas(Atlas):
    """The harness on the financials test universe, without Hindsight (no retains)."""

    def settings(self) -> Settings:
        return super().settings().model_copy(update={"hindsight_url": None})

    def ingest(self, company: str, key: str | None = None) -> str:  # pyright: ignore[reportIncompatibleMethodOverride]
        enqueued = JobQueue(self.engine).enqueue(
            "ingest", key or company, ingest_payload(company, None, None)
        )
        self.worker_pass()
        job = self.get(f"/api/v1/jobs/{enqueued.job.id}")
        assert job["status"] == "succeeded", job["failures"]
        return company

    def checks(self, company: str, as_of: str | None = NOW) -> dict[str, dict[str, Any]]:
        company_id = self.company(company)["id"]
        params = {"as_of": as_of} if as_of else {}
        answer = self.get(f"/api/v1/companies/{company_id}/bear-checks", **params)
        assert answer["company_id"] == company_id
        assert [each["key"] for each in answer["checks"]] == KEYS
        return {each["key"]: each for each in answer["checks"]}

    def record(
        self,
        company: str,
        form: str,
        public_at: str,
        *paragraphs: str,
        name: str | None = None,
        broken: bool = False,
    ) -> str:
        """A filing of `form` public at `public_at`, built from these paragraphs, in the ledger."""
        when = datetime.fromisoformat(public_at)
        accession = f"0000000000-{when:%y}-{uuid.uuid4().int % 10**6:06d}"
        url = f"https://www.sec.gov/Archives/edgar/data/42/{accession}/{name or form}.htm"
        candidate = SourceCandidate(
            provider_id="sec_edgar",
            kind="sec_filing_document",
            url=url,
            title=f"{company} {form} {when:%Y-%m-%d}",
            document_type=form,
            discovered_at=when,
            available_at=when,
            available_at_basis="sec_acceptance",
            language="en",
            filing=SecFiling(
                cik="0000000042",
                company_name=company,
                accession_number=accession,
                form=form,
                filing_date=when.date(),
                report_date=None,
                acceptance_datetime=when,
                primary_document=f"{name or form}.htm",
            ),
        )
        body = "".join(f"<p>{each}</p>" for each in paragraphs)
        # A byte neither UTF-8 nor Windows-1252 makes the parse incomplete (replaced).
        raw = f"<html><body>{body}</body></html>".encode() + (b"\x81" if broken else b"")
        settings = self.settings()
        ledger = SourceLedger(self.engine, open_archive(settings), Actor.from_settings(settings))
        recorded = ledger.record(
            FetchedDocument(
                candidate=candidate,
                url=url,
                fetched_at=when,
                not_modified=False,
                content=raw,
                media_type="text/html",
                validators=HttpValidators(),
                attempts=(),
            ),
            company_id=uuid.UUID(self.company(company)["id"]),
        )
        return str(recorded.source_version_id)

    def parsed(self, version_id: str) -> str:
        response = self.api.get(f"/api/v1/source-versions/{version_id}/content?kind=parsed")
        assert response.status_code == 200, response.text
        return response.text


@pytest.fixture
def atlas(database_url: str, tmp_path: Path) -> Iterator[BearAtlas]:
    harness = BearAtlas(database_url, tmp_path, "http://127.0.0.1:1", themes_config=THEMES)
    seed_companies(harness.settings())  # the financials universe, not the CLI's default one
    yield harness
    harness.engine.dispose()


def observation(atlas: BearAtlas, observation_id: str) -> dict[str, Any]:
    return atlas.get(f"/api/v1/financial-observations/{observation_id}")["observation"]


# --- XBRL: the recorded Lumentum and Coherent filings ---------------------------------------


def test_dilution_and_net_cash_from_the_recorded_lumentum_companyfacts(atlas: BearAtlas) -> None:
    atlas.ingest("lumentum")

    checks = atlas.checks("lumentum")

    # The 10-K's cover: 89.7 million shares at 14 Aug 2026; the 10-K of a year earlier: 69.9
    # million at 12 Aug 2025. 89.7 / 69.9 - 1 = +28.33%, above the 10% line.
    dilution = checks["dilution"]
    assert dilution["status"] == "flag"
    assert dilution["value"]["shares"] == 89_700_000
    assert dilution["value"]["shares_year_earlier"] == 69_900_000
    assert dilution["value"]["growth_pct"] == 28.33
    assert "flag above +10%" in dilution["basis"]
    shares = {
        (o["period_end"], o["concept"], o["value"])
        for o in (observation(atlas, s["observation_id"]) for s in dilution["sources"])
    }
    assert shares == {
        ("2026-08-14", "EntityCommonStockSharesOutstanding", "89700000"),
        ("2025-08-12", "EntityCommonStockSharesOutstanding", "69900000"),
    }

    # The 10-K's balance sheet at 27 Jun 2026: cash 2,043.5 million, debt 1,637.4 million
    # (the filer's own total), no short-term investments tagged: 406.1 million net cash.
    net_cash = checks["net_cash"]
    assert net_cash["status"] == "clear"
    assert net_cash["value"] == {
        "unit": "USD",
        "as_of_balance_sheet": "2026-06-27",
        "net_cash": 406_100_000,
        "cash": 2_043_500_000,
        "short_term_investments": None,
        "debt": 1_637_400_000,
        "debt_concepts": ["DebtLongtermAndShorttermCombinedAmount"],
    }
    assert {s["concept"] for s in net_cash["sources"]} == {
        "us-gaap:CashAndCashEquivalentsAtCarryingValue",
        "us-gaap:DebtLongtermAndShorttermCombinedAmount",
    }


def test_customer_concentration_reads_the_customer_table_of_the_recorded_lumentum_10k(
    atlas: BearAtlas,
) -> None:
    atlas.ingest("lumentum")

    answer = atlas.checks("lumentum")["customer_concentration"]

    # The 10-K's customer note: "Customer A 26.6 % 15.4 % 18.9 %" (fiscal 2026, 2025, 2024) and
    # "Customer B 15.0 % 16.0 % 11.4 %" under "net revenue from a single end customer which
    # represented 10% or more of our total net revenue". The 79.2% of revenue outside the United
    # States of the next paragraph is geography, not a customer.
    assert answer["status"] == "flag"
    assert answer["value"]["current_percent"] == 26.6
    (source,) = answer["sources"]  # only the row at or above 25%
    assert source["quote"] == "Customer A	26.6	%	15.4	%	18.9	%"
    assert source["form_type"] == "10-K"
    text = atlas.parsed(source["source_version_id"])
    assert text[source["char_start"] : source["char_end"]] == source["quote"]
    assert "79.2" not in json.dumps(answer["value"])


def test_a_check_without_its_data_is_unknown_never_clear(atlas: BearAtlas) -> None:
    atlas.ingest("lumentum")

    checks = atlas.checks("lumentum")

    # The fixture has no revenue for the first two quarters of fiscal 2026, so there are not four
    # consecutive quarters of revenue and gross profit ending 27 Jun 2026.
    margin = checks["gaap_gross_margin"]
    assert (margin["status"], margin["value"], margin["sources"]) == ("unknown", None, [])
    assert "four consecutive quarters" in margin["basis"]
    # Atlas ingests 10-K, 10-Q and 8-K only: no shelf form in the ledger proves nothing.
    shelf = checks["shelf_or_atm"]
    assert (shelf["status"], shelf["value"], shelf["sources"]) == ("unknown", None, [])
    assert shelf["basis"].startswith("form not ingested")


def test_gross_margin_over_four_quarters_flags_a_fall_of_more_than_five_points(
    atlas: BearAtlas,
) -> None:
    atlas.ingest("lumentum")

    margin = atlas.checks("lumentum", "2025-01-01T00:00:00Z")["gaap_gross_margin"]

    # Quarters to 28 Sep 2024: revenue 366.8 + 366.5 + 308.3 + 336.9 = 1,378.5 million and gross
    # profit 64.0 + 59.5 + 51.3 + 77.9 = 252.7 million (the fourth quarter of fiscal 2024 is the
    # year less nine months: 1,359.2 - 1,050.9 and 251.5 - 200.2): 18.33%. A year earlier:
    # gross profit 444.5 / revenue 1,577.8 million = 28.17%. A fall of 9.84 points.
    assert margin["status"] == "flag"
    assert margin["value"]["ttm_margin_pct"] == 18.33
    assert margin["value"]["prior_ttm_margin_pct"] == 28.17
    assert margin["value"]["change_points"] == -9.84
    assert [q["period_end"] for q in margin["value"]["quarters"]] == [
        "2023-12-30",
        "2024-03-30",
        "2024-06-29",
        "2024-09-28",
    ]
    assert [q["gross_profit"] for q in margin["value"]["quarters"]] == [
        64_000_000,
        59_500_000,
        51_300_000,
        77_900_000,
    ]
    assert margin["sources"]  # the observations of every quarter, both years
    assert all(s["kind"] == "financial_observation" for s in margin["sources"])


def test_gross_margin_that_rose_is_clear(atlas: BearAtlas) -> None:
    atlas.ingest("lumentum")

    margin = atlas.checks("lumentum", "2025-08-25T00:00:00Z")["gaap_gross_margin"]

    # Fiscal 2025: gross profit 459.9 million on revenue 1,645.0 million = 27.96%, against 18.5%
    # (fiscal 2024: 251.5 / 1,359.2).
    assert margin["status"] == "clear"
    assert margin["value"]["ttm_margin_pct"] == 27.96
    assert margin["value"]["prior_ttm_margin_pct"] == 18.5


def test_xbrl_checks_read_only_what_was_public_by_the_as_of_time(atlas: BearAtlas) -> None:
    atlas.ingest("lumentum")

    # 10 Aug 2026: the 10-Q (6 May) is public, the 10-K (17 Aug) is not.
    before = atlas.checks("lumentum", "2026-08-10T00:00:00Z")
    after = atlas.checks("lumentum", "2026-08-20T00:00:00Z")

    assert before["dilution"]["value"]["shares"] == 77_800_000  # the 10-Q's cover, 30 Apr 2026
    assert after["dilution"]["value"]["shares"] == 89_700_000
    # Net debt at the 10-Q's balance sheet (28 Mar 2026): cash 2,617.8 less debt 3,281.8 million.
    assert before["net_cash"]["status"] == "flag"
    assert before["net_cash"]["value"]["net_cash"] == -664_000_000
    assert after["net_cash"]["status"] == "clear"
    # The 10-K's text is not read before it is public.
    assert before["customer_concentration"]["status"] == "unknown"
    assert after["customer_concentration"]["status"] == "flag"
    assert before["going_concern"]["value"]["document"]["form"] == "10-Q"
    assert after["going_concern"]["value"]["document"]["form"] == "10-K"
    # Every source of the earlier answer was public by then.
    for answer in before.values():
        for source in answer["sources"]:
            if source["kind"] == "financial_observation":
                held = observation(atlas, source["observation_id"])
                assert held["available_at"] <= "2026-08-10T00:00:00Z"
            else:
                assert source["available_at"] <= "2026-08-10T00:00:00Z"


def test_no_data_at_all_is_six_unknowns(atlas: BearAtlas) -> None:
    atlas.ingest("coherent")

    early = atlas.checks("coherent", "2005-01-01T00:00:00Z")
    none = atlas.checks("schema-drift")

    for answer in (*early.values(), *none.values()):
        assert (answer["status"], answer["value"], answer["sources"]) == ("unknown", None, [])
        assert answer["basis"]


def test_coherent_has_no_debt_or_margin_tags_so_those_checks_are_unknown(atlas: BearAtlas) -> None:
    atlas.ingest("coherent")

    checks = atlas.checks("coherent")

    assert checks["dilution"]["status"] == "flag"  # 195.8 million against 155.8 million shares
    assert checks["net_cash"]["status"] == "unknown"  # cash is tagged, debt is not: not zero
    assert "debt" in checks["net_cash"]["basis"]
    assert checks["gaap_gross_margin"]["status"] == "unknown"
    # "We had two customers who each contributed more than 10% of revenue during fiscal 2026."
    concentration = checks["customer_concentration"]
    # "More than 10%" is a lower bound, not a value: no evidence either way, so unknown.
    assert concentration["status"] == "unknown"
    assert concentration["value"]["matches"][0]["lower_bound"] is True


def test_a_figure_older_than_fifteen_months_is_unknown_not_the_old_number(
    atlas: BearAtlas,
) -> None:
    atlas.ingest("lumentum")

    checks = atlas.checks("lumentum", "2028-01-01T00:00:00Z")

    # The last balance sheet is 27 Jun 2026 and the last cover count 14 Aug 2026.
    assert checks["net_cash"]["status"] == "unknown"
    assert checks["dilution"]["status"] == "unknown"
    assert "2026-08-14" in checks["dilution"]["basis"]


def test_as_of_defaults_to_now_and_a_bad_request_is_refused(atlas: BearAtlas) -> None:
    atlas.ingest("lumentum")
    company_id = atlas.company("lumentum")["id"]

    now = atlas.get(f"/api/v1/companies/{company_id}/bear-checks")

    assert abs(datetime.fromisoformat(now["as_of"]) - datetime.now(UTC)) < timedelta(minutes=5)
    assert [c["key"] for c in now["checks"]] == KEYS
    missing = atlas.api.get(f"/api/v1/companies/{uuid.uuid4()}/bear-checks")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"
    naive = atlas.api.get(f"/api/v1/companies/{company_id}/bear-checks?as_of=2026-01-01")
    assert naive.status_code == 422  # an as-of time carries its offset


# --- text: hand-built filings ----------------------------------------------------------------

CONCENTRATION = "In fiscal 2025, Customer A accounted for approximately 31% of our net revenue."
LOW_CONCENTRATION = "Customer B accounted for 12% of our total revenue in fiscal 2026."
GOING_CONCERN = (
    "These conditions raise substantial doubt about our ability to continue as a going concern."
)
NOT_GOING_CONCERN = (
    "Management concluded there is no substantial doubt about our ability to continue as a going"
    " concern."
)


def test_customer_concentration_quotes_the_sentence_of_the_latest_annual_report(
    atlas: BearAtlas,
) -> None:
    tenk = atlas.record("schema-drift", "10-K", "2025-03-01T21:00:00+00:00", FILLER, CONCENTRATION)

    answer = atlas.checks("schema-drift", "2025-06-01T00:00:00Z")["customer_concentration"]

    assert answer["status"] == "flag"
    assert answer["value"]["current_percent"] == 31.0
    (source,) = answer["sources"]
    assert source["source_version_id"] == tenk
    assert source["form_type"] == "10-K"
    assert source["quote"] == CONCENTRATION
    # The span names exactly that sentence in the named parse.
    text = atlas.parsed(tenk)
    assert text[source["char_start"] : source["char_end"]] == CONCENTRATION
    assert answer["value"]["matches"][0]["percents"] == [31.0]


def test_a_later_annual_report_replaces_the_earlier_and_a_future_one_is_not_read(
    atlas: BearAtlas,
) -> None:
    atlas.record("schema-drift", "10-K", "2025-03-01T21:00:00+00:00", FILLER, CONCENTRATION)
    atlas.record("schema-drift", "10-K", "2026-03-01T21:00:00+00:00", FILLER, LOW_CONCENTRATION)

    before_any = atlas.checks("schema-drift", "2025-02-01T00:00:00Z")["customer_concentration"]
    first = atlas.checks("schema-drift", "2025-12-01T00:00:00Z")["customer_concentration"]
    second = atlas.checks("schema-drift", "2026-04-01T00:00:00Z")["customer_concentration"]

    assert before_any["status"] == "unknown"
    assert first["status"] == "flag"  # the 2026 report is not read before it is public
    assert second["status"] == "clear"  # 12% is below the 25% line; the old report is not read
    assert second["value"]["current_percent"] == 12.0
    assert second["sources"][0]["quote"] == LOW_CONCENTRATION


def test_a_20f_is_an_annual_report_and_a_region_is_not_a_customer(atlas: BearAtlas) -> None:
    atlas.record(
        "nokia",
        "20-F",
        "2026-03-05T08:00:00+00:00",
        "During 2025, net revenue from customers outside Finland represented 91% of net sales.",
        "Customer C accounted for 27% of net sales in 2025.",
    )

    answer = atlas.checks("nokia", "2026-04-01T00:00:00Z")["customer_concentration"]

    assert answer["status"] == "flag"
    assert [m["percents"] for m in answer["value"]["matches"]] == [[27.0]]
    assert answer["sources"][0]["form_type"] == "20-F"


def test_going_concern_language_in_the_latest_periodic_report(atlas: BearAtlas) -> None:
    atlas.record("schema-drift", "10-K", "2026-03-01T21:00:00+00:00", FILLER, NOT_GOING_CONCERN)
    tenq = atlas.record("schema-drift", "10-Q", "2026-05-08T21:00:00+00:00", FILLER, GOING_CONCERN)

    older = atlas.checks("schema-drift", "2026-04-01T00:00:00Z")["going_concern"]
    newer = atlas.checks("schema-drift", "2026-06-01T00:00:00Z")["going_concern"]

    # The 10-K says there is no such doubt: clear, and its sentence is listed as such.
    assert older["status"] == "clear"
    assert older["value"]["negated_sentences"] == 1
    assert older["sources"][0]["quote"] == NOT_GOING_CONCERN
    # The 10-Q, public later, is the latest periodic report and names the doubt.
    assert newer["status"] == "flag"
    (source,) = newer["sources"]
    assert source["source_version_id"] == tenq
    assert atlas.parsed(tenq)[source["char_start"] : source["char_end"]] == GOING_CONCERN


def test_shelf_or_offering_filings_in_the_ledger_in_the_twelve_months_flag(
    atlas: BearAtlas,
) -> None:
    old = atlas.record("schema-drift", "S-3", "2025-01-10T15:00:00+00:00", FILLER, name="s3-old")
    recent = atlas.record("schema-drift", "424B5", "2026-02-20T15:00:00+00:00", FILLER, name="p")
    atlas.record("schema-drift", "10-K", "2026-03-01T21:00:00+00:00", FILLER)

    in_window = atlas.checks("schema-drift", "2026-06-01T00:00:00Z")["shelf_or_atm"]
    too_old = atlas.checks("schema-drift", "2025-12-01T00:00:00Z")["shelf_or_atm"]
    not_yet = atlas.checks("schema-drift", "2026-02-01T00:00:00Z")["shelf_or_atm"]

    assert in_window["status"] == "flag"
    assert [f["form"] for f in in_window["value"]["filings"]] == ["424B5"]
    assert [s["source_version_id"] for s in in_window["sources"]] == [recent]
    assert in_window["sources"][0]["char_start"] is None
    # The S-3 of 10 Jan 2025 is within twelve months of 1 Dec 2025.
    assert [s["source_version_id"] for s in too_old["sources"]] == [old]
    assert too_old["status"] == "flag"
    # 1 Feb 2026: the S-3 is over twelve months old and the 424B5 is not yet public. The ledger
    # holds nothing of the window, which proves nothing about what was filed.
    assert not_yet["status"] == "unknown"
    assert not_yet["basis"].startswith("form not ingested")


# --- the MCP tool ----------------------------------------------------------------------------


class Session:
    """The Atlas MCP server over the harness's API."""

    def __init__(self, atlas: BearAtlas) -> None:
        self.atlas = atlas
        self.requests = 0

    def call(self, tool: str, **arguments: Any) -> tuple[bool, dict[str, Any]]:
        self.requests += 1
        response = self.atlas.api.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": self.requests,
                "method": "tools/call",
                "params": {"name": tool, "arguments": arguments},
            },
        )
        assert response.status_code == 200, response.text
        result = response.json()["result"]
        return result["isError"], json.loads(result["content"][0]["text"])

    def open(self, as_of: str, **extra: Any) -> str:
        is_error, opened = self.call(
            "open_session",
            question="Is anything constraining photonics supply?",
            as_of=as_of,
            seeds=["lumentum"],
            model="claude-fable-5-1",
            actor="claude-session",
            **extra,
        )
        assert not is_error, opened
        return opened["session_id"]


def tool_calls(atlas: BearAtlas, session: str) -> list[tuple[str, str, str | None]]:
    from sqlalchemy import text

    with atlas.engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT tool, outcome, reason FROM session_tool_call"
                " WHERE session_id = :id ORDER BY created_at, id"
            ),
            {"id": session},
        ).all()
    return [(row.tool, row.outcome, row.reason) for row in rows if row.tool == "bear_checks"]


def test_the_tool_answers_as_of_the_sessions_time_and_is_counted(atlas: BearAtlas) -> None:
    atlas.ingest("lumentum")
    mcp = Session(atlas)
    early = mcp.open("2026-08-10T00:00:00Z")
    late = mcp.open("2026-09-29T00:00:00Z")

    is_error, before = mcp.call("bear_checks", session_id=early, company="lumentum")
    assert not is_error, before
    _, after = mcp.call("bear_checks", session_id=late, company="lumentum")

    assert before["company"] == "lumentum"
    assert before["as_of"] == "2026-08-10T00:00:00Z"
    assert [c["key"] for c in before["checks"]] == KEYS
    assert "never read it as clear" in before["note"]
    by_key = {c["key"]: c for c in before["checks"]}
    assert by_key["dilution"]["value"]["shares"] == 77_800_000  # the 10-Q's; the 10-K is not public
    assert by_key["net_cash"]["status"] == "flag"
    assert {c["key"]: c for c in after["checks"]}["dilution"]["value"]["shares"] == 89_700_000
    # It is the route's answer, unchanged.
    direct = atlas.checks("lumentum", "2026-08-10T00:00:00Z")
    assert {c["key"]: c for c in before["checks"]} == direct
    assert tool_calls(atlas, early) == [("bear_checks", "ok", None)]


def test_the_tool_takes_no_as_of_and_needs_a_session_and_a_known_company(
    atlas: BearAtlas,
) -> None:
    atlas.ingest("lumentum")
    mcp = Session(atlas)
    listed = atlas.api.post(
        "/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    ).json()["result"]["tools"]
    schema = next(each for each in listed if each["name"] == "bear_checks")["inputSchema"]
    assert set(schema["properties"]) == {"session_id", "company"}
    assert set(schema["required"]) == {"session_id", "company"}
    session = mcp.open(NOW)

    is_error, refused = mcp.call("bear_checks", session_id=session, company="nonesuch")

    assert is_error and refused["refused"] == "unknown_company"
    is_error, _ = mcp.call(
        "bear_checks", session_id=session, company="lumentum", as_of="2020-01-01T00:00:00Z"
    )
    assert is_error  # no tool takes an as-of time
    assert tool_calls(atlas, session) == [
        ("bear_checks", "refused", "unknown_company"),
        ("bear_checks", "refused", "invalid_arguments"),
    ]


def test_an_isolated_session_is_refused_the_tool(atlas: BearAtlas) -> None:
    atlas.ingest("lumentum")
    mcp = Session(atlas)
    isolated = mcp.open(NOW, isolated=True)

    is_error, refused = mcp.call("bear_checks", session_id=isolated, company="lumentum")

    assert is_error
    assert refused["refused"] == "isolated_session"
    assert tool_calls(atlas, isolated) == [("bear_checks", "refused", "isolated_session")]


# --- clear only on positive evidence ------------------------------------------------------------


def test_a_report_with_no_customer_share_is_unknown_and_a_whole_one_without_the_phrase_clear(
    atlas: BearAtlas,
) -> None:
    atlas.record("schema-drift", "10-K", "2026-03-01T21:00:00+00:00", FILLER)

    checks = atlas.checks("schema-drift", "2026-04-01T00:00:00Z")

    assert checks["customer_concentration"]["status"] == "unknown"
    assert checks["customer_concentration"]["sources"] == []
    # Going concern: the whole 10-K was read and the phrase is not in it.
    assert checks["going_concern"]["status"] == "clear"
    assert "whole" in checks["going_concern"]["basis"]


def test_the_statement_that_no_customer_exceeded_ten_percent_is_clear_with_its_span(
    atlas: BearAtlas,
) -> None:
    sentence = "No single customer accounted for more than 10% of our revenue in fiscal 2026."
    tenk = atlas.record("schema-drift", "10-K", "2026-03-01T21:00:00+00:00", FILLER, sentence)

    answer = atlas.checks("schema-drift", "2026-04-01T00:00:00Z")["customer_concentration"]

    assert answer["status"] == "clear"
    (source,) = answer["sources"]
    assert source["quote"] == sentence
    assert atlas.parsed(tenk)[source["char_start"] : source["char_end"]] == sentence
    assert answer["value"]["no_customer_above"] == [10.0]


def test_a_partly_parsed_report_that_flags_nothing_is_unknown_and_one_that_flags_still_flags(
    atlas: BearAtlas,
) -> None:
    atlas.record(
        "schema-drift",
        "10-K",
        "2026-03-01T21:00:00+00:00",
        FILLER,
        "No single customer accounted for more than 10% of our revenue.",
        broken=True,
    )
    atlas.record("nokia", "20-F", "2026-03-01T21:00:00+00:00", FILLER, CONCENTRATION, GOING_CONCERN)
    atlas.record(
        "coherent",
        "10-K",
        "2026-03-01T21:00:00+00:00",
        FILLER,
        CONCENTRATION,
        GOING_CONCERN,
        broken=True,
    )

    partial = atlas.checks("schema-drift", "2026-04-01T00:00:00Z")
    flagged = atlas.checks("coherent", "2026-04-01T00:00:00Z")

    assert partial["customer_concentration"]["status"] == "unknown"
    assert "partly parsed" in partial["customer_concentration"]["basis"]
    assert partial["going_concern"]["status"] == "unknown"
    assert "partly parsed" in partial["going_concern"]["basis"]
    # A flag in the part read stands.
    assert flagged["customer_concentration"]["status"] == "flag"
    assert flagged["going_concern"]["status"] == "flag"


def test_going_concern_that_is_not_alleviated_or_is_conditional_still_flags(
    atlas: BearAtlas,
) -> None:
    atlas.record(
        "schema-drift",
        "10-Q",
        "2026-05-08T21:00:00+00:00",
        FILLER,
        "The new facility has not alleviated the substantial doubt about our ability to"
        " continue as a going concern.",
    )
    atlas.record(
        "nokia",
        "10-Q",
        "2026-05-08T21:00:00+00:00",
        FILLER,
        "Without additional financing, there is substantial doubt about the ability of the"
        " Company to continue as a going concern.",
    )

    for company in ("schema-drift", "nokia"):
        assert atlas.checks(company, "2026-06-01T00:00:00Z")["going_concern"]["status"] == "flag"


def test_the_current_period_share_decides_and_a_group_is_reported_apart(
    atlas: BearAtlas,
) -> None:
    atlas.record(
        "schema-drift",
        "10-K",
        "2026-03-01T21:00:00+00:00",
        FILLER,
        "Customer A accounted for 12%, 30% and 22% of our revenue in fiscal 2026, 2025 and 2024.",
        "Our ten largest customers accounted for 62% of our net revenue in fiscal 2026.",
    )

    answer = atlas.checks("schema-drift", "2026-04-01T00:00:00Z")["customer_concentration"]

    # Customer A's fiscal 2026 share is 12% (the 30% was a year earlier): below the line. The
    # ten largest together are 62%, which is a group, not one customer, and not a flag.
    assert answer["status"] == "clear"
    assert answer["value"]["current_percent"] == 12.0
    (group,) = answer["value"]["top_customers_share"]
    assert group["current_percent"] == 62.0
