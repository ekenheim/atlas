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
from tests.fakes.edgar_fts import FakeEdgarFullTextSearch, FilingReply
from tests.fakes.searxng import FakeSearXNG, SearchReply
from tests.fakes.serve import serve
from tests.fakes.web import IR, WEB_SITES, recent_web
from tests.harness import THEMES, make_settings

Q4 = f"{IR}/news/q4-results.html"  # public 2026-08-11T20:05Z
QUESTION = "Is indium phosphide laser capacity the constraint?"
SEPTEMBER = "2026-09-30T00:00:00Z"
QUOTE = "Demand for our indium phosphide lasers exceeded our capacity in the quarter"
NEW_TOOLS = {"filing_search", "web_search", "fetch_page"}
EML_QUERY = "Coherent EML laser chip capacity 200G per lane 800G transceiver"


class Mcp:
    def __init__(
        self, database_url: str, tmp_path: Path, web: Path, searxng_url: str, edgar_url: str
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
            searxng_url=searxng_url,
            sec_user_agent="Atlas Research watch-test@example.com",
            sec_efts_url=f"{edgar_url}/LATEST",
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
def moment() -> datetime:
    return datetime.now(UTC)


@pytest.fixture
def mcp(
    database_url: str,
    tmp_path: Path,
    moment: datetime,
    searxng: tuple[FakeSearXNG, str],
    edgar: tuple[FakeEdgarFullTextSearch, str],
) -> Iterator[Mcp]:
    harness = Mcp(database_url, tmp_path, recent_web(tmp_path, moment), searxng[1], edgar[1])
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
    assert "another session" in refused["message"] and refused["fetched_at"]
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


# --- an isolated session ------------------------------------------------------------------------


def test_an_isolated_session_is_refused_all_three_tools_before_anything_happens(
    mcp: Mcp,
    searxng: tuple[FakeSearXNG, str],
    edgar: tuple[FakeEdgarFullTextSearch, str],
) -> None:
    isolated = mcp.open(SEPTEMBER, isolated=True)

    for tool, arguments in (
        ("filing_search", {"query": "InP substrates"}),
        ("web_search", {"query": "InP"}),
        ("fetch_page", {"company": "lumentum", "url": Q4}),
    ):
        refused = mcp.refused(tool, "isolated_session", session_id=isolated, **arguments)
        assert tool in refused["message"]

    # Nothing was searched, requested or recorded.
    assert searxng[0].calls == [] and edgar[0].calls == []
    assert mcp.scalar("SELECT count(*) FROM source_document") == 0
    assert mcp.scalar("SELECT count(*) FROM discovery_query") == 0
    assert mcp.scalar("SELECT count(*) FROM fetch_gate_decision") == 0
    assert mcp.calls(isolated)[1:] == [
        ("filing_search", "refused", "isolated_session"),
        ("web_search", "refused", "isolated_session"),
        ("fetch_page", "refused", "isolated_session"),
    ]
