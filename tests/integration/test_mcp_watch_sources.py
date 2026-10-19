"""The MCP tools for primary sources beyond filings (W3): `filing_search`, `web_search`,
`fetch_page`, and the routes under them (`GET /api/v1/filing-search`, `GET /api/v1/web-search`).

Seam: the HTTP endpoint of the API (JSON-RPC over the TestClient) on a fresh database. EDGAR
full-text search and SearXNG are the transport-level fakes of `tests/fakes` served on localhost
(the API builds its clients from settings), the pages the hand-written fixtures of
`tests/fixtures/web/` replayed in process. Nothing is requested from the network.
"""

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from atlas.api.app import create_app
from atlas.audit import Actor
from atlas.jobs import JobQueue, Worker, builtin_registry
from atlas.ledger.ingest import INGEST_KIND, ingest_payload
from tests.fakes.edgar_fts import FakeEdgarFullTextSearch, FilingReply
from tests.fakes.identity import FakeIdentitySources
from tests.fakes.searxng import FakeSearXNG, SearchReply
from tests.fakes.serve import serve
from tests.fakes.web import IR, WEB_SITES, recent_web
from tests.harness import EDGAR_FIXTURES, THEMES, make_settings

Q4 = f"{IR}/news/q4-results.html"  # public 2026-08-11T20:05Z
QUESTION = "Is indium phosphide laser capacity the constraint?"
SEPTEMBER = "2026-09-30T00:00:00Z"
QUOTE = "Demand for our indium phosphide lasers exceeded our capacity in the quarter"
NEW_TOOLS = {"filing_search", "web_search", "fetch_page"}
EML_QUERY = "Coherent EML laser chip capacity 200G per lane 800G transceiver"


class Mcp:
    def __init__(
        self,
        database_url: str,
        tmp_path: Path,
        web: Path,
        searxng_url: str,
        edgar_url: str,
        identity_url: str,
    ):
        archive = tmp_path / "archive"
        archive.mkdir(exist_ok=True)
        self.engine = create_engine(database_url)
        self.settings = make_settings(
            archive,
            database_url=database_url,
            actor="watch-test",
            themes_config=THEMES,
            source_sites_config=WEB_SITES,
            exchange_fixtures_dir=web,
            sec_fixtures_dir=EDGAR_FIXTURES,  # an EDGAR Archives URL is fetched with SEC's client
            searxng_url=searxng_url,
            sec_user_agent="Atlas Research watch-test@example.com",
            sec_efts_url=f"{edgar_url}/LATEST",
            # Entity resolution of a company by name (W9): the identity fake, never SEC itself.
            sec_files_url=f"{identity_url}/files",
            sec_data_url=identity_url,
            gleif_url=f"{identity_url}/api/v1",
            openfigi_url=identity_url,
            retention_triage="off",
        )
        self.api = TestClient(create_app(self.settings))
        self.requests = 0

    def rpc(self, method: str, params: dict[str, Any] | None = None) -> Any:
        self.requests += 1
        return self.api.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": self.requests, "method": method, "params": params or {}},
        )

    def call(self, tool: str, **arguments: Any) -> tuple[bool, dict[str, Any]]:
        response = self.rpc("tools/call", {"name": tool, "arguments": arguments})
        assert response.status_code == 200, response.text
        result = response.json()["result"]
        return result["isError"], json.loads(result["content"][0]["text"])

    def ok(self, tool: str, **arguments: Any) -> dict[str, Any]:
        is_error, value = self.call(tool, **arguments)
        assert not is_error, value
        return value

    def refused(self, tool: str, code: str, **arguments: Any) -> dict[str, Any]:
        is_error, value = self.call(tool, **arguments)
        assert is_error and value.get("refused") == code, value
        return value

    def get(self, path: str, **params: Any) -> Any:
        response = self.api.get(path, params=params)
        assert response.status_code == 200, response.text
        return response.json()

    def open(self, as_of: str = SEPTEMBER, **extra: Any) -> str:
        return self.ok("open_session", question=QUESTION, as_of=as_of, **extra)["session_id"]

    def leads(self, origin: str) -> list[dict[str, Any]]:
        return self.get("/api/v1/leads", origin=origin, theme="photonics", limit=100)["items"]

    def scalar(self, sql: str, **params: Any) -> Any:
        with self.engine.connect() as connection:
            return connection.execute(text(sql), params).scalar_one()

    def calls(self, session: str) -> list[tuple[str, str, str | None]]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT tool, outcome, reason FROM session_tool_call"
                    " WHERE session_id = :id ORDER BY created_at, id"
                ),
                {"id": session},
            ).all()
        return [(row.tool, row.outcome, row.reason) for row in rows]


@pytest.fixture
def searxng() -> Iterator[tuple[FakeSearXNG, str]]:
    fake = FakeSearXNG()
    with serve(fake.handle) as served:
        yield fake, served.url
        served.raise_errors()


@pytest.fixture
def edgar() -> Iterator[tuple[FakeEdgarFullTextSearch, str]]:
    fake = FakeEdgarFullTextSearch()
    with serve(fake.handle) as served:
        yield fake, served.url
        served.raise_errors()


@pytest.fixture
def identity() -> Iterator[tuple[FakeIdentitySources, str]]:
    fake = FakeIdentitySources()
    with serve(fake.handle) as served:
        yield fake, served.url
        served.raise_errors()


@pytest.fixture
def moment() -> datetime:
    return datetime.now(UTC)


@pytest.fixture
def mcp(
    database_url: str,
    tmp_path: Path,
    moment: datetime,
    searxng: tuple[FakeSearXNG, str],
    edgar: tuple[FakeEdgarFullTextSearch, str],
    identity: tuple[FakeIdentitySources, str],
) -> Iterator[Mcp]:
    harness = Mcp(
        database_url,
        tmp_path,
        recent_web(tmp_path, moment),
        searxng[1],
        edgar[1],
        identity[1],
    )
    yield harness
    harness.engine.dispose()


# --- the tools ---------------------------------------------------------------------------------


def test_the_three_tools_are_listed_typed_and_take_no_as_of(mcp: Mcp) -> None:
    listed = {each["name"]: each for each in mcp.rpc("tools/list").json()["result"]["tools"]}

    assert NEW_TOOLS <= set(listed)
    for name in NEW_TOOLS:
        schema = listed[name]["inputSchema"]
        assert schema["additionalProperties"] is False
        assert "session_id" in schema["required"]
        assert "as_of" not in schema["properties"]
        assert listed[name]["description"]


# --- filing_search -----------------------------------------------------------------------------


def test_filing_search_stores_every_hit_as_a_lead_and_returns_its_id(
    mcp: Mcp, edgar: tuple[FakeEdgarFullTextSearch, str]
) -> None:
    fake, _ = edgar
    fake.script('"InP substrates"', FilingReply.of("inp-substrates-10k"))
    session = mcp.open(SEPTEMBER)

    found = mcp.ok(
        "filing_search", session_id=session, query="InP substrates", forms=["10-K"], limit=10
    )

    assert found["total"] == 4 and found["new_leads"] == 4
    assert [(h["filer"], h["form"], h["filed"]) for h in found["hits"]] == [
        ("AXT INC", "10-K", "2026-03-17"),
        ("Aeluma, Inc.", "10-K", "2026-09-16"),
        ("Aeluma, Inc.", "10-K", "2025-09-09"),
        ("COHERENT CORP.", "10-K", "2026-08-14"),
    ]
    first = found["hits"][0]
    assert (first["cik"], first["ticker"]) == ("0001051627", "AXTI")
    assert first["url"].endswith("/1051627/000143774926008612/axti20251231_10k.htm")
    assert "never a Fact" in found["note"]
    # The search EDGAR was asked: the phrase quoted, the forms, and a year to the last filing day
    # that was certainly over at the as-of instant (30 September 00:00Z: the 28th).
    assert fake.searches()[0] == {
        "q": '"InP substrates"',
        "forms": "10-K",
        "dateRange": "custom",
        "startdt": "2025-09-28",
        "enddt": "2026-09-28",
    }
    # Stored as leads of origin edgar_fts, in the session's theme, with their filing.
    leads = {each["id"]: each for each in mcp.leads("edgar_fts")}
    assert {h["lead_id"] for h in found["hits"]} == set(leads)
    lead = leads[first["lead_id"]]
    assert lead["tier"] == "C" and lead["filing"]["cik"] == "0001051627"
    assert lead["filing"]["accession"] == "0001437749-26-008612"
    assert lead["published_date"] == "2026-03-17"
    assert lead["theme"] == "photonics" and lead["query"] == '"InP substrates"'


def test_filing_search_end_is_bounded_by_the_sessions_as_of_instant(
    mcp: Mcp, edgar: tuple[FakeEdgarFullTextSearch, str]
) -> None:
    fake, _ = edgar
    fake.script('"InP substrates"', FilingReply.of("no-hits"))
    session = mcp.open("2026-03-01T12:00:00Z")

    found = mcp.ok("filing_search", session_id=session, query="InP substrates", end="2026-12-31")

    # 1 March 12:00Z: filings of the 1st may still be coming; the 28th of February are in.
    assert found["window"] == {"start": "2025-02-28", "end": "2026-02-28", "clamped_to_as_of": True}
    assert fake.searches()[0]["enddt"] == "2026-02-28"
    assert found["hits"] == [] and found["total"] == 0


def test_filing_search_refuses_a_window_that_starts_after_the_as_of_instants_last_day(
    mcp: Mcp, edgar: tuple[FakeEdgarFullTextSearch, str]
) -> None:
    fake, _ = edgar
    session = mcp.open("2026-03-01T12:00:00Z")

    refused = mcp.refused(
        "filing_search", "window_after_as_of", session_id=session, query="InP", start="2026-04-01"
    )

    assert refused["start"] == "2026-04-01"
    assert fake.calls == []  # EDGAR was not asked
    mcp.refused(
        "filing_search",
        "invalid_window",
        session_id=session,
        query="InP",
        start="2025-06-01",
        end="2025-01-01",
    )


def test_a_repeated_filing_search_finds_the_same_leads(
    mcp: Mcp, edgar: tuple[FakeEdgarFullTextSearch, str]
) -> None:
    fake, _ = edgar
    fake.script(
        '"InP substrates"',
        FilingReply.of("inp-substrates-10k"),
        FilingReply.of("inp-substrates-aeluma-coherent"),
    )
    session = mcp.open(SEPTEMBER)

    first = mcp.ok("filing_search", session_id=session, query="InP substrates")
    again = mcp.ok("filing_search", session_id=session, query="InP substrates")

    assert again["new_leads"] == 0
    first_ids = {h["accession"]: h["lead_id"] for h in first["hits"]}
    assert {h["lead_id"] for h in again["hits"]} <= set(first_ids.values())
    assert len(mcp.leads("edgar_fts")) == 4
    assert (
        mcp.calls(session) == [("open_session", "ok", None)] + [("filing_search", "ok", None)] * 2
    )


def test_the_filing_search_route_records_the_search_with_its_session(
    mcp: Mcp, edgar: tuple[FakeEdgarFullTextSearch, str]
) -> None:
    fake, _ = edgar
    fake.script('"VCSEL"', FilingReply.of("vcsel-lidar"))
    session = mcp.open(SEPTEMBER)

    answer = mcp.get(
        "/api/v1/filing-search",
        q="VCSEL",  # one word: the caller asked, so it is searched
        forms="20-F,10-K",
        start="2026-01-01",
        end="2026-06-30",
        session_id=session,
    )

    assert answer["forms"] == ["20-F", "10-K"] and answer["total"] == 2
    assert fake.searches()[0]["forms"] == "20-F,10-K"
    row = mcp.scalar(
        "SELECT row_to_json(q) FROM (SELECT d.session_id::text, d.theme, d.status, d.new_leads,"
        " d.discovery_id, e.start_date::text, e.end_date::text, e.status AS edgar_status,"
        " e.total_hits FROM discovery_query d JOIN edgar_search e"
        " ON e.discovery_query_id = d.id) q"
    )
    assert row == {
        "session_id": session,
        "theme": "photonics",
        "status": "searched",
        "new_leads": 2,
        "discovery_id": None,
        "start_date": "2026-01-01",
        "end_date": "2026-06-30",
        "edgar_status": "searched",
        "total_hits": 2,
    }
    assert mcp.get("/api/v1/discoveries")["total"] == 0  # a discovery's reads never see it


def test_the_filing_search_route_checks_its_arguments(
    mcp: Mcp, edgar: tuple[FakeEdgarFullTextSearch, str]
) -> None:
    reversed_window = mcp.api.get(
        "/api/v1/filing-search", params={"q": "x y", "start": "2026-02-01", "end": "2026-01-01"}
    )
    unknown = mcp.api.get(
        "/api/v1/filing-search",
        params={"q": "x y", "session_id": "00000000-0000-4000-8000-000000000000"},
    )

    assert reversed_window.status_code == 422
    assert reversed_window.json()["error"]["code"] == "invalid_window"
    assert unknown.status_code == 404
    assert edgar[0].calls == []


def test_a_failed_filing_search_is_an_error_and_is_recorded_failed(
    mcp: Mcp, edgar: tuple[FakeEdgarFullTextSearch, str]
) -> None:
    fake, _ = edgar
    fake.script('"InP substrates"', FilingReply.error(403))
    session = mcp.open(SEPTEMBER)

    is_error, value = mcp.call("filing_search", session_id=session, query="InP substrates")

    assert is_error and value["error"] == "search_failed"
    assert mcp.scalar("SELECT status FROM edgar_search") == "failed"
    assert mcp.leads("edgar_fts") == []
    assert mcp.calls(session)[-1] == ("filing_search", "error", "search_failed")


# --- web_search --------------------------------------------------------------------------------


def test_web_search_stores_results_as_leads_with_their_publication_date(
    mcp: Mcp, searxng: tuple[FakeSearXNG, str]
) -> None:
    fake, _ = searxng
    fake.script(EML_QUERY, SearchReply.of("coherent-eml-capacity"))
    session = mcp.open("2026-09-10T00:00:00Z")

    found = mcp.ok("web_search", session_id=session, query=EML_QUERY)

    # Engines and language come from the settings, as a discovery's search sends them.
    assert fake.searches()[0] == {
        "q": EML_QUERY,
        "format": "json",
        "engines": "bing,brave",
        "language": "en",
    }
    assert found["total"] == 7 and found["engines"] == ["bing", "brave"]
    # The 15 September article dates itself after the session's as-of date: left out, not stored.
    assert found["dropped_after_as_of"] == 1
    urls = [each["url"] for each in found["results"]]
    assert len(urls) == 6 and not any("coherent-200g-eml" in url for url in urls)
    trade = next(each for each in found["results"] if "eml-capacity-race" in each["url"])
    assert trade["published"] == "2026-09-02" and trade["new"] is True
    assert trade["title"] and trade["snippet"] and trade["engines"] == ["bing"]
    undated = next(each for each in found["results"] if "wikipedia" in each["url"])
    assert undated["published"] is None  # no date to bound it by: a lead like the rest
    # Stored as searxng leads of the session's theme, one per canonical URL.
    stored = {each["id"]: each for each in mcp.leads("searxng")}
    assert {each["lead_id"] for each in found["results"]} == set(stored)
    assert stored[trade["lead_id"]]["published_date"] == "2026-09-02"
    assert stored[trade["lead_id"]]["query"] == EML_QUERY
    assert not any("coherent-200g-eml" in each["canonical_url"] for each in stored.values())


def test_web_results_are_one_lead_per_canonical_url_across_searches(
    mcp: Mcp, searxng: tuple[FakeSearXNG, str]
) -> None:
    fake, _ = searxng
    fake.script(
        "indium phosphide substrate capacity expansion 2026",
        SearchReply.of("inp-substrate-capacity"),
    )
    fake.script(
        "InP laser second source qualification hyperscaler",
        SearchReply.of("inp-laser-second-source"),
    )
    session = mcp.open(SEPTEMBER)

    first = mcp.ok(
        "web_search", session_id=session, query="indium phosphide substrate capacity expansion 2026"
    )
    second = mcp.ok(
        "web_search", session_id=session, query="InP laser second source qualification hyperscaler"
    )

    # The ftp:// result is no web URL: no lead. The tracking parameters, the upper-case host, the
    # default port, `www.` and the fragment do not make a second lead of the same article.
    assert len(first["results"]) == 2 and first["new_leads"] == 2
    axt = next(each for each in first["results"] if "axt-expands" in each["url"])
    again = next(each for each in second["results"] if "axt-expands" in each["url"])
    assert again["lead_id"] == axt["lead_id"] and again["new"] is False
    assert second["new_leads"] == 1
    assert second["unresponsive_engines"] == [{"engine": "brave", "reason": "timeout"}]
    leads = mcp.leads("searxng")
    assert len(leads) == 3
    by_id = {each["id"]: each for each in leads}
    assert by_id[axt["lead_id"]]["sightings"] == 2
    assert by_id[axt["lead_id"]]["canonical_url"] == (
        "https://photonics-news.test/2026/08/axt-expands-inp-substrate-capacity"
    )


def test_a_failed_web_search_is_an_error_not_a_refusal(
    mcp: Mcp, searxng: tuple[FakeSearXNG, str]
) -> None:
    fake, _ = searxng
    fake.script("x", SearchReply.error(403))
    session = mcp.open(SEPTEMBER)

    is_error, value = mcp.call("web_search", session_id=session, query="x")

    assert is_error and value["error"] == "search_failed" and "403" in value["message"]
    assert mcp.scalar("SELECT status FROM discovery_query") == "failed"
    assert mcp.leads("searxng") == []


def test_the_web_search_route_works_without_a_session(
    mcp: Mcp, searxng: tuple[FakeSearXNG, str]
) -> None:
    fake, _ = searxng
    fake.script(EML_QUERY, SearchReply.of("coherent-eml-capacity"))

    answer = mcp.get(
        "/api/v1/web-search", q=EML_QUERY, theme="photonics", published_by="2026-09-10", limit=2
    )

    assert len(answer["results"]) == 2 and answer["dropped_after_bound"] == 1
    assert len(mcp.leads("searxng")) == 2
    assert mcp.scalar("SELECT session_id FROM discovery_query") is None


# --- fetch_page --------------------------------------------------------------------------------

RECENT = f"{IR}/news/recent-meta.html"  # dated one day before the test's moment: believed
TOPIC = "indium phosphide lasers capacity"


def zulu(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


def when(value: str) -> datetime:
    return datetime.fromisoformat(value)


def test_fetch_page_archives_a_page_the_fetching_session_can_read_and_quote(
    mcp: Mcp, moment: datetime
) -> None:
    # The session is as of half a day ago. The page is dated yesterday (within a week of the
    # fetch, so believed) and was fetched now, after the as-of time, by this very session.
    as_of = moment - timedelta(hours=12)
    session = mcp.open(zulu(as_of))

    page = mcp.ok("fetch_page", session_id=session, company="lumentum", url=RECENT)

    assert page["fetched"] is True and page["outcome"] == "new_version"
    assert page["tier"] == "A" and page["readable"] is True
    assert when(page["available_at"]) == moment - timedelta(days=1)
    assert (page["available_at_basis"], page["date_source"]) == (
        "page_published_date",
        "article_published_time",
    )
    detail = mcp.get(f"/api/v1/source-versions/{page['version_id']}")
    assert detail["metadata"]["web"]["site"] == "example-issuer"
    assert [each["session_id"] for each in detail["fetches"]] == [session]
    assert when(detail["fetched_at"]) > as_of  # fetched after the session's as-of time
    # The page can be read and quoted as any archived document.
    window = mcp.ok("read", session_id=session, version_id=page["version_id"], start=0, end=600)
    assert QUOTE in window["text"]
    mcp.ok("locate", session_id=session, version_id=page["version_id"], quote=QUOTE)
    fact = mcp.ok(
        "record_fact",
        session_id=session,
        version_id=page["version_id"],
        quote=QUOTE,
        step="constraint",
        status="in_effect",
        statement="Example Issuer says demand for its indium phosphide lasers exceeded capacity.",
    )
    assert fact["recorded"] is True


def test_an_old_dated_page_fetched_today_is_not_readable_by_an_earlier_session(
    mcp: Mcp,
) -> None:
    session = mcp.open(SEPTEMBER)  # the page is dated 11 August 2026, long before its fetch

    page = mcp.ok("fetch_page", session_id=session, company="lumentum", url=Q4)

    # Not believed: it is public from when Atlas fetched it, which is after the session's time.
    assert page["available_at_basis"] == "observed_discovery"
    assert page["date_source"] == "fetch_time"
    assert page["readable"] is False and "cannot read" in page["note"]
    assert when(page["available_at"]) > when(SEPTEMBER)
    recorded = mcp.get(f"/api/v1/source-versions/{page['version_id']}")  # it is in the ledger
    assert recorded["metadata"]["web"]["date_as_written"] == "2026-08-11T20:05:00+00:00"
    refused = mcp.refused(
        "read",
        "available_after_as_of",
        session_id=session,
        version_id=page["version_id"],
        start=0,
        end=100,
    )
    assert refused["version"] == page["version_id"]


def test_a_page_with_no_date_of_its_own_is_unreadable_to_a_session_as_of_an_earlier_time(
    mcp: Mcp,
) -> None:
    session = mcp.open("2026-08-01T00:00:00Z")

    page = mcp.ok(
        "fetch_page", session_id=session, company="lumentum", url=f"{IR}/news/no-date.html"
    )

    assert (
        page["available_at_basis"] == "observed_discovery" and page["date_source"] == "fetch_time"
    )
    assert page["readable"] is False


def test_a_page_this_session_fetched_is_readable_by_it_and_not_by_another_as_of_the_same_time(
    mcp: Mcp, moment: datetime
) -> None:
    as_of = zulu(moment - timedelta(hours=12))
    fetcher, other = mcp.open(as_of), mcp.open(as_of)
    page = mcp.ok("fetch_page", session_id=fetcher, company="lumentum", url=RECENT)
    version = page["version_id"]

    mcp.ok("read", session_id=fetcher, version_id=version, start=0, end=100)
    refused = mcp.refused(
        "read", "available_after_as_of", session_id=other, version_id=version, start=0, end=100
    )
    mcp.refused(
        "locate", "available_after_as_of", session_id=other, version_id=version, quote=QUOTE
    )
    mcp.refused(
        "record_fact",
        "available_after_as_of",
        session_id=other,
        version_id=version,
        quote=QUOTE,
        step="constraint",
        status="in_effect",
        statement="Example Issuer says demand for its lasers exceeded capacity.",
    )
    assert "within 36 hours" in refused["message"] and refused["fetched_at"]
    # Asking for the page itself makes it that session's too (an unchanged fetch, its own record).
    again = mcp.ok("fetch_page", session_id=other, company="lumentum", url=RECENT)
    assert again["outcome"] == "unchanged" and again["version_id"] == version
    assert again["readable"] is True
    mcp.ok("read", session_id=other, version_id=version, start=0, end=100)
    fetches = mcp.get(f"/api/v1/source-versions/{version}")["fetches"]
    assert sorted(each["session_id"] for each in fetches) == sorted([fetcher, other])


def test_search_and_newest_documents_show_a_page_only_to_a_session_that_may_read_it(
    mcp: Mcp, moment: datetime
) -> None:
    as_of = zulu(moment - timedelta(hours=12))
    fetcher, other = mcp.open(as_of), mcp.open(as_of)
    later = mcp.open(zulu(moment + timedelta(days=1)))  # as of after the fetch: it was public
    page = mcp.ok("fetch_page", session_id=fetcher, company="lumentum", url=RECENT)

    def seen(session: str) -> tuple[list[str], list[str]]:
        found = mcp.ok("search", session_id=session, company="lumentum", q=TOPIC)
        listed = mcp.ok("newest_documents", session_id=session, companies=["lumentum"])
        return (
            [each["source_version_id"] for each in found["hits"]],
            [each["source_version_id"] for each in listed["documents"]],
        )

    assert seen(fetcher) == ([page["version_id"]], [page["version_id"]])
    assert seen(other) == ([], [])
    assert seen(later) == ([page["version_id"]], [page["version_id"]])
    mcp.ok("read", session_id=later, version_id=page["version_id"], start=0, end=100)


UNDATED = f"{IR}/news/no-date.html"  # no date of its own: available from its fetch


def test_an_undated_page_fetched_by_a_prospective_session_is_readable_by_that_session_alone(
    mcp: Mcp, moment: datetime
) -> None:
    # As of an hour ago, the Watch's start; the page is available from its fetch, a little later.
    as_of = zulu(moment - timedelta(hours=1))
    fetcher, other = mcp.open(as_of), mcp.open(as_of)

    page = mcp.ok("fetch_page", session_id=fetcher, company="lumentum", url=UNDATED)
    version = page["version_id"]

    assert page["date_source"] == "fetch_time" and when(page["available_at"]) > when(as_of)
    assert page["readable"] is True
    window = mcp.ok("read", session_id=fetcher, version_id=version, start=0, end=300)
    assert "long-term supply agreements" in window["text"]
    found = mcp.ok("search", session_id=fetcher, company="lumentum", q="long-term supply")
    assert [each["source_version_id"] for each in found["hits"]] == [version]
    mcp.refused(
        "read", "available_after_as_of", session_id=other, version_id=version, start=0, end=9
    )
    searched = mcp.ok("search", session_id=other, company="lumentum", q="long-term supply")
    assert searched["hits"] == []


def test_a_session_older_than_36_hours_before_its_fetch_does_not_read_what_it_fetched(
    mcp: Mcp, moment: datetime
) -> None:
    near = mcp.open(zulu(moment - timedelta(hours=35)))
    replay = mcp.open(zulu(moment - timedelta(hours=40)))

    kept = mcp.ok("fetch_page", session_id=near, company="lumentum", url=UNDATED)
    past = mcp.ok("fetch_page", session_id=replay, company="lumentum", url=UNDATED)

    assert kept["readable"] is True
    # The same page, now fetched by a session as of 40 hours ago: it asked, it does not qualify.
    assert past["outcome"] == "unchanged" and past["readable"] is False
    mcp.refused(
        "read",
        "available_after_as_of",
        session_id=replay,
        version_id=past["version_id"],
        start=0,
        end=9,
    )
    found = mcp.ok("search", session_id=replay, company="lumentum", q="long-term supply")
    assert found["hits"] == []


def test_the_board_takes_a_fact_of_a_page_only_from_a_session_that_may_read_the_page(
    mcp: Mcp, moment: datetime
) -> None:
    # Integration of W1 and W3: the board's Fact rule is the MCP tools' rule, web pages included.
    # The Watch fetches an undated page (public from its fetch, after the session's as-of time),
    # records a Fact of it and makes it a step's primary evidence.
    as_of = zulu(moment - timedelta(hours=1))
    watch, other = mcp.open(as_of), mcp.open(as_of)
    undated = mcp.ok("fetch_page", session_id=watch, company="lumentum", url=UNDATED)
    dated = mcp.ok("fetch_page", session_id=watch, company="lumentum", url=RECENT)
    assert when(undated["available_at"]) > when(as_of) and undated["readable"] is True
    facts = [
        mcp.ok(
            "record_fact",
            session_id=watch,
            version_id=page["version_id"],
            quote=quote,
            step="constraint",
            status="in_effect",
            statement=statement,
        )["fact_id"]
        for page, quote, statement in (
            (
                undated,
                "Our lasers are sold under long-term supply agreements.",
                "Example Issuer says its lasers are sold under long-term supply agreements.",
            ),
            (dated, QUOTE, "Example Issuer says demand for its lasers exceeded capacity."),
        )
    ]
    for fact in facts:
        chokepoint = mcp.ok("add_chokepoint", session_id=watch, constraint=fact, layer="l")["id"]
        primary = {"step": "a", "status": "primary", "evidence": {"fact_ids": [fact]}}
        mcp.ok(
            "update_chokepoint", session_id=watch, id=chokepoint, kind="step_set", payload=primary
        )
        # Another session as of the same time did not fetch the page, so cannot cite its Fact,
        # whether the page's own date is after its as-of time (undated) or before it (dated).
        theirs = mcp.ok("add_chokepoint", session_id=other, constraint=fact, layer="m")["id"]
        refused = mcp.refused(
            "update_chokepoint",
            "fact_available_after_as_of",
            session_id=other,
            id=theirs,
            kind="step_set",
            payload=primary,
        )
        assert refused["fact"] == fact


def test_a_page_fetched_for_an_isolated_session_is_not_readable_by_it(
    mcp: Mcp, moment: datetime
) -> None:
    as_of = zulu(moment - timedelta(hours=1))
    isolated = mcp.open(as_of, isolated=True)
    # The tool refuses an isolated session; the route does not know, so ask it directly.
    asked = mcp.api.post(
        "/api/v1/sources/fetch",
        json={"company": "lumentum", "url": UNDATED, "session_id": isolated},
    )
    assert asked.status_code == 200, asked.text
    version = asked.json()["source_version_id"]

    mcp.refused("read", "isolated_session", session_id=isolated, version_id=version, start=0, end=9)
    searched = mcp.ok("search", session_id=isolated, company="lumentum", q="long-term supply")
    assert searched["hits"] == [] and searched["documents_searched"] == 0


def test_an_isolated_session_sees_no_web_version(mcp: Mcp, moment: datetime) -> None:
    # As of tomorrow, so the as-of rules alone would show it: only the isolation hides it.
    tomorrow = zulu(moment + timedelta(days=1))
    fetcher = mcp.open(tomorrow)
    page = mcp.ok("fetch_page", session_id=fetcher, company="lumentum", url=RECENT)
    version = page["version_id"]
    isolated = mcp.open(tomorrow, isolated=True)

    searched = mcp.ok("search", session_id=isolated, company="lumentum", q=TOPIC)

    assert searched["hits"] == [] and searched["documents_searched"] == 0
    for tool, arguments in (
        ("read", {"start": 0, "end": 100}),
        ("locate", {"quote": QUOTE}),
        (
            "record_fact",
            {
                "quote": QUOTE,
                "step": "constraint",
                "status": "in_effect",
                "statement": "Example Issuer says demand for its lasers exceeded capacity.",
            },
        ),
    ):
        refused = mcp.refused(
            tool, "isolated_session", session_id=isolated, version_id=version, **arguments
        )
        assert refused["version"] == version
    # The Fact the other session recorded is not the isolated session's to get either.
    fact = mcp.ok(
        "record_fact",
        session_id=fetcher,
        version_id=version,
        quote=QUOTE,
        step="constraint",
        status="in_effect",
        statement="Example Issuer says demand for its lasers exceeded capacity.",
    )
    mcp.refused("get_fact", "fact_not_in_session", session_id=isolated, fact_id=fact["fact_id"])
    # And a session that is not isolated reads it, as before.
    mcp.ok("read", session_id=fetcher, version_id=version, start=0, end=100)


def test_fetch_page_is_refused_by_the_gate_and_nothing_is_recorded(mcp: Mcp) -> None:
    session = mcp.open(SEPTEMBER)

    unknown = mcp.refused(
        "fetch_page",
        "fetch_blocked",
        session_id=session,
        company="lumentum",
        url="https://unknown.example-offsite.test/a",
    )
    forbidden = mcp.refused(
        "fetch_page",
        "fetch_blocked",
        session_id=session,
        company="lumentum",
        url="https://www.example-forbidden.test/news",
    )
    robots = mcp.refused(
        "fetch_page",
        "fetch_blocked",
        session_id=session,
        company="lumentum",
        url=f"{IR}/private/roadmap.html",
    )

    assert [unknown["blocked_by"], forbidden["blocked_by"], robots["blocked_by"]] == [
        "register",
        "terms",
        "robots",
    ]
    assert mcp.scalar("SELECT count(*) FROM source_document") == 0
    assert mcp.scalar("SELECT count(*) FROM fetch_gate_decision WHERE status = 'blocked'") == 3
    assert mcp.calls(session)[1:] == [("fetch_page", "refused", "fetch_blocked")] * 3
    mcp.refused("fetch_page", "unknown_company", session_id=session, company="nobody", url=Q4)
    other = mcp.ok(
        "fetch_page", session_id=session, company="lumentum", url=f"{IR}/news/explicit.html"
    )
    assert other["fetched"] is True
    mcp.refused(
        "fetch_page",
        "url_belongs_to_other_company",
        session_id=session,
        company="coherent",
        url=f"{IR}/news/explicit.html",
    )


# --- W9: the Watch's reach ----------------------------------------------------------------------

TRADE = "https://news.example-trade.test/2026/10/nvidia-optics-allocation.html"
TRADE_QUOTE = (
    "NVIDIA said its supply of co-packaged optical engines will remain allocated through next year."
)
NOTICE = "https://www.example-regulator.test/notices/magnet-export-licences.html"
NOTICE_QUOTE = (
    "Exports of rare earth permanent magnets will require an individual export licence from"
    " 1 December 2026."
)
NVIDIA_CIK = "0001045810"  # SEC's ticker file and submissions in tests/fixtures/identity
# Lumentum's FY2026 10-K in the recorded EDGAR fixtures: accepted 2026-08-17T20:03:17Z.
TEN_K = "https://www.sec.gov/Archives/edgar/data/1633978/000162828026057358/lite-20260627.htm"
TEN_K_QUOTE = (
    "We operate within global markets characterized by robust, long-term growth trends that are"
    " increasing demand for our products and technologies."
)


def step_with_lead(lead: str) -> dict[str, Any]:
    return {"step": "a", "status": "lead", "evidence": {"lead_ids": [lead]}}


def test_a_step_cites_a_lead_its_own_search_found_after_its_as_of_time(
    mcp: Mcp, searxng: tuple[FakeSearXNG, str], moment: datetime
) -> None:
    # The Watch's as-of time is its start, so every lead its searches find is first seen after
    # it. A lead the session's own search found counts; one another session found does not.
    fake, _ = searxng
    fake.script(
        EML_QUERY, SearchReply.of("coherent-eml-capacity"), SearchReply.of("coherent-eml-capacity")
    )
    as_of = zulu(moment - timedelta(hours=1))
    watch, other = mcp.open(as_of), mcp.open(as_of)
    found = mcp.ok("web_search", session_id=watch, query=EML_QUERY)
    lead = next(each["lead_id"] for each in found["results"] if "eml-capacity-race" in each["url"])
    mine = mcp.ok("add_chokepoint", session_id=watch, constraint="EML chips", layer="l")["id"]
    theirs = mcp.ok("add_chokepoint", session_id=other, constraint="EML chips", layer="m")["id"]

    mcp.ok(
        "update_chokepoint",
        session_id=watch,
        id=mine,
        kind="step_set",
        payload=step_with_lead(lead),
    )
    refused = mcp.refused(
        "update_chokepoint",
        "created_after_as_of",
        session_id=other,
        id=theirs,
        kind="step_set",
        payload=step_with_lead(lead),
    )

    assert refused["lead"] == lead
    # The board's reads follow the same rule: the finder sees its lead, the other session not.
    seen = mcp.get(f"/api/v1/chokepoints/{mine}", session_id=watch)
    assert [each["id"] for each in seen["leads"]] == [lead]
    assert mcp.get(f"/api/v1/chokepoints/{mine}", session_id=other)["leads"] == []
    # Seeing it again in its own search makes it the other session's find too.
    mcp.ok("web_search", session_id=other, query=EML_QUERY)
    mcp.ok(
        "update_chokepoint",
        session_id=other,
        id=theirs,
        kind="step_set",
        payload=step_with_lead(lead),
    )


def test_a_lead_dated_after_the_as_of_time_is_refused_even_to_the_session_that_found_it(
    mcp: Mcp, searxng: tuple[FakeSearXNG, str], moment: datetime
) -> None:
    fake, _ = searxng
    fake.script(EML_QUERY, SearchReply.of("coherent-eml-capacity"))
    as_of = moment - timedelta(hours=1)
    watch = mcp.open(zulu(as_of))
    found = mcp.ok("web_search", session_id=watch, query=EML_QUERY)
    late, today = (
        next(each["lead_id"] for each in found["results"] if part in each["url"])
        for part in ("eml-capacity-race", "wikipedia")
    )
    # Stored by another process with a later day than the session's search would have kept
    # (the first sighting's date is the lead's): two days on, and the as-of day itself, which a
    # date alone does not show was over by the as-of instant.
    with mcp.engine.begin() as connection:
        for lead, day in ((late, moment + timedelta(days=2)), (today, as_of)):
            connection.execute(
                text("UPDATE lead SET published_date = :day WHERE id = :id"),
                {"day": day.astimezone(UTC).date(), "id": lead},
            )
    chokepoint = mcp.ok("add_chokepoint", session_id=watch, constraint="c", layer="l")["id"]

    for lead in (late, today):
        refused = mcp.refused(
            "update_chokepoint",
            "published_after_as_of",
            session_id=watch,
            id=chokepoint,
            kind="step_set",
            payload=step_with_lead(lead),
        )
        assert refused["lead"] == lead


def test_fetch_page_by_name_and_cik_keeps_a_counterparty_and_its_page_is_quoted(
    mcp: Mcp, moment: datetime, identity: tuple[FakeIdentitySources, str]
) -> None:
    session = mcp.open(zulu(moment - timedelta(hours=1)))

    page = mcp.ok("fetch_page", session_id=session, company_name="NVIDIA", cik="1045810", url=TRADE)

    assert (page["outcome"], page["company"], page["tier"]) == ("new_version", "nvidia", "B")
    assert page["readable"] is True
    company = mcp.get(f"/api/v1/companies/{page['company_id']}")
    assert (company["role"], company["cik"], company["lei"]) == ("counterparty", NVIDIA_CIK, None)
    assert (company["legal_name"], company["display_name"]) == ("NVIDIA CORP", "NVIDIA")
    assert company["counterparty"]["source"] == "sec"
    assert company["source_path"] is None
    assert any(path.endswith(f"/submissions/CIK{NVIDIA_CIK}.json") for path in identity[0].paths())
    fact = mcp.ok(
        "record_fact",
        session_id=session,
        version_id=page["version_id"],
        quote=TRADE_QUOTE,
        step="constraint",
        status="in_effect",
        statement="A trade report says NVIDIA's optical engine supply stays allocated next year.",
    )
    assert fact["recorded"] is True
    recorded = mcp.get(f"/api/v1/facts/{fact['fact_id']}")
    assert recorded["assertion"]["subject_company_id"] == page["company_id"]
    # By its name alone it is now the company Atlas has: no second counterparty.
    again = mcp.ok("fetch_page", session_id=session, company_name="NVIDIA", url=TRADE)
    assert (again["company_id"], again["outcome"]) == (page["company_id"], "unchanged")
    assert [c["slug"] for c in mcp.get("/api/v1/companies", role="counterparty")["items"]] == [
        "nvidia"
    ]
    # A counterparty is never a theme's company nor a session's seed.
    theme = mcp.get("/api/v1/themes/photonics/map")
    members = [c["slug"] for layer in theme["layers"] for c in layer["companies"]]
    assert "nvidia" not in members + [c["slug"] for c in theme["unlayered"]]
    mcp.refused(
        "open_session", "unknown_company", question=QUESTION, as_of=SEPTEMBER, seeds=["nvidia"]
    )


def test_fetch_page_refuses_a_name_its_identifier_does_not_have_and_asks_for_one_company(
    mcp: Mcp,
) -> None:
    session = mcp.open(SEPTEMBER)

    wrong = mcp.refused(
        "fetch_page",
        "unresolved_company",
        session_id=session,
        company_name="Huawei",
        cik=NVIDIA_CIK,
        url=TRADE,
    )
    assert "none of the names" in wrong["message"]
    for arguments in (
        {"company": "lumentum", "company_name": "NVIDIA"},
        {"company": "lumentum", "publisher": True},
        {},
        {"company": "lumentum", "cik": NVIDIA_CIK},
    ):
        mcp.refused("fetch_page", "invalid_company", session_id=session, url=TRADE, **arguments)
    assert mcp.scalar("SELECT count(*) FROM company WHERE role <> 'researched'") == 0
    assert mcp.scalar("SELECT count(*) FROM source_document") == 0


def test_a_publisher_only_fetch_archives_a_government_notice_quoted_as_a_fact(
    mcp: Mcp, moment: datetime
) -> None:
    session = mcp.open(zulu(moment - timedelta(hours=1)))

    page = mcp.ok("fetch_page", session_id=session, publisher=True, url=NOTICE)

    # The register gives the site `public_regulatory`: the regulator's own notice, Tier A.
    assert (page["company"], page["tier"], page["readable"]) == (
        "publisher-example-regulator",
        "A",
        True,
    )
    publisher = mcp.get(f"/api/v1/companies/{page['company_id']}")
    assert publisher["role"] == "publisher"
    assert publisher["display_name"] == "Example Ministry of Commerce (synthetic)"
    assert (publisher["cik"], publisher["source_path"], publisher["counterparty"]) == (
        None,
        None,
        None,
    )
    version = mcp.get(f"/api/v1/source-versions/{page['version_id']}")
    assert version["source_document"]["license_class"] == "public_regulatory"
    fact = mcp.ok(
        "record_fact",
        session_id=session,
        version_id=page["version_id"],
        quote=NOTICE_QUOTE,
        step="constraint",
        status="regulatory",
        statement="Rare earth magnet exports need an export licence from 1 December 2026.",
    )
    assert fact["recorded"] is True
    # The same publisher again: one company per site.
    again = mcp.ok("fetch_page", session_id=session, publisher=True, url=NOTICE)
    assert again["company_id"] == page["company_id"]
    assert mcp.scalar("SELECT count(*) FROM company WHERE role = 'publisher'") == 1
    # A publisher is never in a theme, never a seed and never ingested.
    theme = mcp.get("/api/v1/themes/photonics/map")
    members = [c["slug"] for layer in theme["layers"] for c in layer["companies"]]
    assert page["company"] not in members + [c["slug"] for c in theme["unlayered"]]
    assert page["company"] not in [c["slug"] for c in theme["counterparties"]]
    mcp.refused(
        "open_session",
        "unknown_company",
        question=QUESTION,
        as_of=SEPTEMBER,
        seeds=[page["company"]],
    )
    seeded = mcp.api.post(
        "/api/v1/sessions",
        json={
            "question": QUESTION,
            "theme": "photonics",
            "seed_company_ids": [page["company_id"]],
            "as_of": SEPTEMBER,
        },
    )
    assert seeded.status_code == 422 and seeded.json()["error"]["code"] == "unknown_company"
    queue = JobQueue(mcp.engine, actor=Actor("watch-test"))
    job = queue.enqueue(
        INGEST_KIND, "publisher", ingest_payload(page["company"], None, None), max_attempts=1
    )
    assert Worker(queue, builtin_registry(mcp.settings)).run_once() == 1
    failed = mcp.get(f"/api/v1/jobs/{job.job.id}")
    assert failed["status"] == "failed" and "publisher" in failed["failures"][-1]["error"]


def test_a_publisher_only_fetch_of_an_unregistered_site_is_blocked_and_creates_nothing(
    mcp: Mcp,
) -> None:
    session = mcp.open(SEPTEMBER)

    blocked = mcp.refused(
        "fetch_page",
        "fetch_blocked",
        session_id=session,
        publisher=True,
        url="https://unknown.example-offsite.test/notice",
    )

    assert blocked["blocked_by"] == "register"
    assert mcp.scalar("SELECT count(*) FROM company WHERE role = 'publisher'") == 0


def test_an_edgar_filing_fetched_for_its_filer_is_tier_a_from_its_acceptance(
    mcp: Mcp, moment: datetime
) -> None:
    session = mcp.open(zulu(moment - timedelta(hours=1)))

    page = mcp.ok("fetch_page", session_id=session, company="lumentum", url=TEN_K)

    # Asked with SEC's client: the page and the submissions index replay from Lumentum's
    # recorded EDGAR fixtures (the web fixtures hold no sec.gov URL).
    assert (page["outcome"], page["tier"], page["readable"]) == ("new_version", "A", True)
    assert (page["available_at_basis"], page["date_source"]) == (
        "sec_acceptance",
        "sec_submissions",
    )
    assert when(page["available_at"]) == when("2026-08-17T20:03:17Z")
    version = mcp.get(f"/api/v1/source-versions/{page['version_id']}")
    assert version["source_document"]["license_class"] == "public_issuer"
    assert version["metadata"]["web"]["site"] == "sec-edgar"
    fact = mcp.ok(
        "record_fact",
        session_id=session,
        version_id=page["version_id"],
        quote=TEN_K_QUOTE,
        step="demand_vs_supply",
        status="in_effect",
        statement="Lumentum says long-term growth trends are increasing demand for its products.",
    )
    assert fact["recorded"] is True


# --- an isolated session ------------------------------------------------------------------------


def test_an_isolated_session_is_refused_all_three_tools_before_anything_happens(
    mcp: Mcp,
    searxng: tuple[FakeSearXNG, str],
    edgar: tuple[FakeEdgarFullTextSearch, str],
    identity: tuple[FakeIdentitySources, str],
) -> None:
    isolated = mcp.open(SEPTEMBER, isolated=True)

    for tool, arguments in (
        ("filing_search", {"query": "InP substrates"}),
        ("web_search", {"query": "InP"}),
        ("fetch_page", {"company": "lumentum", "url": Q4}),
        # W9's new ways (a company by name and CIK, a publisher, an EDGAR filing) too.
        ("fetch_page", {"company_name": "NVIDIA", "cik": NVIDIA_CIK, "url": TRADE}),
        ("fetch_page", {"publisher": True, "url": NOTICE}),
        ("fetch_page", {"company": "lumentum", "url": TEN_K}),
    ):
        refused = mcp.refused(tool, "isolated_session", session_id=isolated, **arguments)
        assert tool in refused["message"]

    # Nothing was searched, resolved, requested or recorded.
    assert searxng[0].calls == [] and edgar[0].calls == [] and identity[0].calls == []
    assert mcp.scalar("SELECT count(*) FROM source_document") == 0
    assert mcp.scalar("SELECT count(*) FROM discovery_query") == 0
    assert mcp.scalar("SELECT count(*) FROM fetch_gate_decision") == 0
    assert mcp.scalar("SELECT count(*) FROM company WHERE role <> 'researched'") == 0
    assert (
        mcp.calls(isolated)[1:]
        == [
            ("filing_search", "refused", "isolated_session"),
            ("web_search", "refused", "isolated_session"),
        ]
        + [("fetch_page", "refused", "isolated_session")] * 4
    )
