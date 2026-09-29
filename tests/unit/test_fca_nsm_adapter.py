"""The FCA NSM adapter (Phase 3-6a ticket 05) at the transport boundary, and the committed
site register's decisions for IQE's sources.

The responses are the hand-written fixtures in `tests/fixtures/fca-nsm/iqe/`
(`scripts/make_fca_nsm_fixtures.py`: the NSM's search and document shapes as served on
2026-09-29, not recorded; identifiers and documents synthetic). Expected values are read off
the fixture rows by hand (NSM times are UTC).
"""

import asyncio
import json
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx2
import pytest

from atlas.sources import FetchError, SearchQuery, SecHttpClient, SourceCandidate, TokenBucket
from atlas.sources.fca_nsm import FcaNsmAdapter
from atlas.sources.gate import FetchBlocked, FetchGate, GatedHttpClient, load_site_register

REPO = Path(__file__).parents[2]
FIXTURES = REPO / "tests" / "fixtures" / "fca-nsm" / "iqe"
SITES = REPO / "configs" / "sources" / "sites.yaml"
SEARCH = "https://api.data.fca.org.uk/search?index=nsm-search"
ARTEFACTS = "https://data.fca.org.uk/artefacts"
INTERIM = f"{ARTEFACTS}/NSM/RNS/5a1f0c3e-0000-4000-8000-000000000001.html"
VOTING = f"{ARTEFACTS}/NSM/RNS/5a1f0c3e-0000-4000-8000-000000000002.html"
FORM_83 = f"{ARTEFACTS}/NSM/RNS/5a1f0c3e-0000-4000-8000-000000000003.html"
ANNUAL = f"{ARTEFACTS}/NSM/Portal/NI-000900001/NI-000900001.pdf"
IQE_LEI = "213800Y33WHD3ESJJP16"
NOW = datetime(2026, 9, 29, 3, 0, 0, 250000, tzinfo=UTC)
UA = "AtlasResearch tests@example.invalid"


class Nsm:
    """Serves the search (a different body per request, if given), the documents and the
    robots.txt answers; records every request and each search's JSON body."""

    def __init__(self, searches: list[bytes] | None = None) -> None:
        self.searches = searches or [(FIXTURES / "search.json").read_bytes()]
        self.requests: list[tuple[str, str]] = []
        self.bodies: list[Any] = []

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        url = str(request.url)
        self.requests.append((request.method, url))
        if url == SEARCH and request.method == "POST":
            self.bodies.append(json.loads(request.content))
            body = self.searches.pop(0) if len(self.searches) > 1 else self.searches[0]
            return httpx2.Response(200, content=body, headers={"Content-Type": "application/json"})
        if url.endswith("/robots.txt"):
            return httpx2.Response(403, content=b"Forbidden")
        path = FIXTURES / url.removeprefix(f"{ARTEFACTS}/")
        if url.startswith(ARTEFACTS) and path.is_file():
            kind = "application/pdf" if url.endswith(".pdf") else "text/html;charset=UTF-8"
            return httpx2.Response(200, content=path.read_bytes(), headers={"Content-Type": kind})
        return httpx2.Response(404)


def client(nsm: Nsm) -> SecHttpClient:
    return SecHttpClient(
        UA, transport=httpx2.MockTransport(nsm.handle), limiter=TokenBucket(math.inf)
    )


def run(nsm: Nsm, query: SearchQuery, fetch: bool = False) -> Any:
    async def go() -> Any:
        async with client(nsm) as http:
            adapter = FcaNsmAdapter(http, lei=IQE_LEI, now=lambda: NOW)
            candidates = await adapter.discover(query)
            if fetch:
                return [await adapter.fetch(c) for c in candidates]
            return candidates

    return asyncio.run(go())


def fixture_rows() -> list[dict[str, Any]]:
    answer = json.loads((FIXTURES / "search.json").read_bytes())
    return [hit["_source"] for hit in answer["hits"]["hits"]]


def answer(rows: list[dict[str, Any]], total: int | None = None) -> bytes:
    hits = [{"_index": "fca-nsm-searchdata", "_id": r["seq_id"], "_source": r} for r in rows]
    value = len(rows) if total is None else total
    return json.dumps(
        {"hits": {"total": {"relation": "eq", "value": value}, "hits": hits}}
    ).encode()


def test_discovery_lists_the_issuers_own_documents_with_their_publication_time() -> None:
    candidates: list[SourceCandidate] = run(Nsm(), SearchQuery())

    # The Form 8.3 is Barclays' disclosure naming IQE as related issuer: not IQE's document.
    assert [(c.url, c.available_at) for c in candidates] == [
        (INTERIM, datetime(2026, 9, 7, 6, 0, 6, tzinfo=UTC)),
        (VOTING, datetime(2026, 9, 1, 15, 0, 0, tzinfo=UTC)),
        (ANNUAL, datetime(2026, 5, 29, 14, 30, tzinfo=UTC)),
    ]
    interim = candidates[0]
    assert interim.provider_id == "fca_nsm"
    assert interim.kind == "exchange_announcement"
    assert interim.available_at_basis == "publisher_timestamp"
    assert interim.title == "IQE plc: H1 2026 Interim Results"
    assert interim.document_type == "Half-year Financial Report"
    assert interim.language is None  # the parse decides
    assert interim.discovered_at == NOW
    announcement = interim.announcement
    assert announcement is not None
    assert announcement.publisher == "FCA National Storage Mechanism"
    assert announcement.announcement_id == "5a1f0c3e-0000-4000-8000-000000000001"
    assert announcement.issuer_code == IQE_LEI
    assert announcement.issuer_name == "IQE PLC"
    assert announcement.category == "Half-year Financial Report"
    assert announcement.published_local == "2026-09-07T06:00:06Z"
    assert announcement.published_at == datetime(2026, 9, 7, 6, 0, 6, tzinfo=UTC)
    assert announcement.timezone == "UTC"
    assert announcement.file_type == "HTML"
    assert candidates[2].announcement is not None
    assert candidates[2].announcement.file_type == "PDF"


def test_the_search_is_the_nsm_pages_own_query_for_the_lei() -> None:
    nsm = Nsm()

    run(nsm, SearchQuery())

    assert nsm.requests == [("POST", SEARCH)]
    # No fractional seconds in `to`: the one shape known to work.
    until = {"from": None, "to": "2026-09-29T03:00:00Z"}
    assert nsm.bodies == [
        {
            "from": 0,
            "size": 100,
            "sort": "submitted_date",
            "sortorder": "desc",
            "criteriaObj": {
                "criteria": [
                    {"name": "company_lei", "value": ["", IQE_LEI, "disclose_org", "related_org"]},
                    {"name": "latest_flag", "value": "Y"},
                ],
                "dateCriteria": [
                    {"name": "publication_date", "value": until},
                    {"name": "submitted_date", "value": until},
                ],
            },
        }
    ]  # fmt: skip


def test_since_and_limit_bound_discovery() -> None:
    after_june = run(Nsm(), SearchQuery(since=datetime(2026, 6, 1, tzinfo=UTC)))
    newest = run(Nsm(), SearchQuery(limit=1))

    assert [c.url for c in after_june] == [INTERIM, VOTING]
    assert [c.url for c in newest] == [INTERIM]


def test_without_a_publication_time_the_submission_time_then_discovery_is_used() -> None:
    rows = fixture_rows()
    rows[0] = rows[0] | {"publication_date": ""}
    rows[1] = rows[1] | {"publication_date": None, "submitted_date": None}

    candidates = run(Nsm([answer(rows)]), SearchQuery())

    interim, voting = candidates[0], candidates[1]
    assert interim.available_at == datetime(2026, 9, 7, 6, 12, 29, tzinfo=UTC)
    assert interim.available_at_basis == "publisher_timestamp"
    assert interim.announcement is not None
    assert interim.announcement.published_local == "2026-09-07T06:12:29Z"
    assert voting.available_at == NOW
    assert voting.available_at_basis == "observed_discovery"
    assert voting.announcement is not None
    assert voting.announcement.published_at is None
    assert voting.announcement.published_local is None


def test_nanosecond_times_are_read() -> None:
    rows = fixture_rows()
    rows[3] = rows[3] | {"publication_date": "2026-05-29T14:30:00.123456789Z"}

    candidates = run(Nsm([answer(rows)]), SearchQuery())

    assert candidates[-1].available_at == datetime(2026, 5, 29, 14, 30, 0, 123456, tzinfo=UTC)


def test_rows_that_are_not_html_or_pdf_documents_are_skipped() -> None:
    rows = fixture_rows()
    rows[0] = rows[0] | {"download_link": "NSM/ESEF/NI-000900002/iqe-2025-12-31.zip"}
    rows[1] = rows[1] | {"download_link": ""}

    candidates = run(Nsm([answer(rows)]), SearchQuery())

    assert [c.url for c in candidates] == [ANNUAL]


def own_row(index: int, submitted: datetime) -> dict[str, Any]:
    stamp = submitted.strftime("%Y-%m-%dT%H:%M:%SZ")
    return fixture_rows()[0] | {
        "seq_id": f"row-{index}",
        "download_link": f"NSM/RNS/row-{index}.html",
        "publication_date": stamp,
        "submitted_date": stamp,
    }


def test_pages_are_asked_for_until_since_is_reached() -> None:
    first = [own_row(i, datetime(2026, 9, 1, tzinfo=UTC)) for i in range(100)]
    second = [own_row(100, datetime(2026, 8, 1, tzinfo=UTC))] + [
        own_row(101 + i, datetime(2026, 5, 1, tzinfo=UTC)) for i in range(99)
    ]
    nsm = Nsm([answer(first, 900), answer(second, 900)])

    candidates = run(nsm, SearchQuery(since=datetime(2026, 6, 1, tzinfo=UTC)))

    assert [body["from"] for body in nsm.bodies] == [0, 100]  # not the rest of the 900
    assert len(candidates) == 101


def test_the_last_page_ends_discovery() -> None:
    rows = [own_row(i, datetime(2026, 9, 1, tzinfo=UTC)) for i in range(100)]
    nsm = Nsm([answer(rows, 130), answer(rows[:30], 130)])

    candidates = run(nsm, SearchQuery())

    assert [body["from"] for body in nsm.bodies] == [0, 100]
    assert len(candidates) == 130


def test_more_than_the_row_cap_fails_rather_than_dropping_announcements() -> None:
    rows = [own_row(i, datetime(2026, 9, 1, tzinfo=UTC)) for i in range(100)]
    nsm = Nsm([answer(rows, 5000)])

    with pytest.raises(FetchError, match="more than 2000 documents"):
        run(nsm, SearchQuery())

    assert len(nsm.bodies) == 20


@pytest.mark.parametrize(
    "body",
    [
        b"<html>maintenance</html>",
        b'{"hits": {"total": 3}}',
        b'{"hits": {"total": {"value": 1}, "hits": [{"_source": 3}]}}',
    ],
)
def test_an_unexpected_search_answer_fails_discovery(body: bytes) -> None:
    with pytest.raises(FetchError, match="the NSM search answered something unexpected"):
        run(Nsm([body]), SearchQuery())


def test_fetch_returns_the_documents_as_served() -> None:
    fetched = run(Nsm(), SearchQuery(), fetch=True)

    interim, annual = fetched[0], fetched[2]
    assert interim.url == INTERIM
    assert interim.media_type == "text/html"
    assert interim.content == (FIXTURES / INTERIM.removeprefix(f"{ARTEFACTS}/")).read_bytes()
    assert annual.media_type == "application/pdf"
    assert annual.content == (FIXTURES / ANNUAL.removeprefix(f"{ARTEFACTS}/")).read_bytes()


# --- the committed site register ---


def gated(nsm: Nsm, url: str, *, post: bool = False) -> Any:
    """The gate's decision for one request under the committed register."""

    async def go() -> Any:
        async with client(nsm) as http:
            gate = FetchGate(load_site_register(SITES), http, now=lambda: NOW)
            gated_client = GatedHttpClient(http, gate)
            try:
                if post:
                    await gated_client.post_json(url, {})
                else:
                    await gated_client.get(url)
            except FetchBlocked as blocked:
                return blocked.decision
            except FetchError:
                pass
            (decision,) = gated_client.take_decisions()
            return decision

    return asyncio.run(go())


def test_the_nsm_is_allowed_by_its_terms_and_its_absent_robots_txt() -> None:
    nsm = Nsm()

    search = gated(nsm, SEARCH, post=True)
    document = gated(nsm, INTERIM)

    for decision in (search, document):
        assert decision.status == "allowed"
        assert decision.site == "fca-nsm"
        assert decision.terms.automation == "allowed"
        assert decision.terms.url == "https://data.fca.org.uk/artefacts/NSM_Terms_of_Use.pdf"
        assert "for any lawful purpose" in decision.terms.note
        assert decision.robots.status == 403  # RFC 9309: unavailable, so no restrictions
        assert decision.reason.startswith("terms allow automation; robots.txt:")
    assert search.robots.url == "https://api.data.fca.org.uk/robots.txt"
    assert document.robots.url == "https://data.fca.org.uk/robots.txt"
    assert ("POST", SEARCH) in nsm.requests


@pytest.mark.parametrize(
    "url",
    [
        "https://www.londonstockexchange.com/news-article/IQE/h1-2026-interim-results/17000000",
        "https://www.londonstockexchange.com/en-gb/news",
        "https://api.londonstockexchange.com/api/gw/lse/instruments/alldata/IQE",
    ],
)
def test_lse_rns_is_blocked_by_its_terms_without_a_request(url: str) -> None:
    nsm = Nsm()

    decision = gated(nsm, url)

    assert decision.status == "blocked"
    assert decision.blocked_by == "terms"
    assert decision.site == "lse-rns"
    assert decision.reason == (
        "blocked: LSE disclaimer limits RNS to personal use stored off any network, and"
        " robots.txt disallows /en-gb/ (an RNS data licence or written consent required)"
    )
    assert decision.terms.url == "https://www.londonstockexchange.com/disclaimer"
    assert decision.robots is None
    assert nsm.requests == []


def test_iqes_brighter_ir_iframe_is_blocked_without_a_request() -> None:
    nsm = Nsm()

    decision = gated(nsm, "https://polaris.brighterir.com/public/iqe/news/rns")

    assert decision.status == "blocked"
    assert decision.blocked_by == "terms"
    assert decision.site == "iqe-brighter-ir"
    assert decision.reason == "iqe-brighter-ir's terms have not been checked"
    assert nsm.requests == []
