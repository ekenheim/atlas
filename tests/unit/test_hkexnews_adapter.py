"""The HKEXnews adapter (Phase 3-6a ticket 04) at the transport boundary.

The responses are the hand-written fixtures in `tests/fixtures/hkexnews/innolight/`
(`scripts/make_hkexnews_fixtures.py`: HKEXnews' documented title-search shape, not
recorded). Expected values are read off the fixture rows by hand: `DATE_TIME` is Hong Kong
time (UTC+8, no daylight saving).
"""

import asyncio
import json
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx2
import pytest

from atlas.sources import FetchError, SearchQuery, SecHttpClient, SourceCandidate, TokenBucket
from atlas.sources.hkexnews import HkexNewsAdapter

FIXTURES = Path(__file__).parents[2] / "tests" / "fixtures" / "hkexnews" / "innolight"
SEARCH = "https://www1.hkexnews.hk/search/titleSearchServlet.do"
BASE = "https://www1.hkexnews.hk/listedco/listconews/sehk/2026"
NOW = datetime(2026, 9, 29, 3, 0, tzinfo=UTC)  # 11:00 in Hong Kong


class Feed:
    """Serves the search (optionally a different body per request) and the PDFs."""

    def __init__(self, searches: list[bytes] | None = None) -> None:
        self.searches = searches or [(FIXTURES / "search.json").read_bytes()]
        self.requests: list[str] = []

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        url = str(request.url)
        self.requests.append(url)
        if url.startswith(SEARCH):
            body = self.searches.pop(0) if len(self.searches) > 1 else self.searches[0]
            return httpx2.Response(200, content=body, headers={"Content-Type": "application/json"})
        path = FIXTURES / urlsplit(url).path.lstrip("/")
        if path.is_file():
            return httpx2.Response(
                200, content=path.read_bytes(), headers={"Content-Type": "application/pdf"}
            )
        return httpx2.Response(404)


def run(feed: Feed, query: SearchQuery, fetch: bool = False) -> Any:
    async def go() -> Any:
        async with SecHttpClient(
            "AtlasResearch tests@example.invalid",
            transport=httpx2.MockTransport(feed.handle),
            limiter=TokenBucket(math.inf),
        ) as client:
            adapter = HkexNewsAdapter(client, stock_id="1000311764", now=lambda: NOW)
            candidates = await adapter.discover(query)
            if fetch:
                return [await adapter.fetch(c) for c in candidates]
            return candidates

    return asyncio.run(go())


def search_params(url: str) -> dict[str, str]:
    return {key: values[0] for key, values in parse_qs(urlsplit(url).query, True).items()}


def test_discovery_lists_each_document_with_hkexnews_publication_time() -> None:
    feed = Feed()

    candidates: list[SourceCandidate] = run(feed, SearchQuery())

    assert [(c.url, c.available_at) for c in candidates] == [
        (f"{BASE}/0904/2026090400456.pdf", datetime(2026, 9, 4, 11, 5, tzinfo=UTC)),
        (f"{BASE}/0821/2026082101227.pdf", datetime(2026, 8, 21, 14, 30, tzinfo=UTC)),
        (f"{BASE}/0729/2026072900123.pdf", datetime(2026, 7, 29, 15, 0, tzinfo=UTC)),
    ]
    interim = candidates[1]
    assert interim.provider_id == "hkexnews"
    assert interim.kind == "exchange_announcement"
    assert interim.available_at_basis == "publisher_timestamp"
    assert interim.title == "INTERIM RESULTS ANNOUNCEMENT FOR THE SIX MONTHS ENDED 30 JUNE 2026"
    assert interim.document_type == "Announcements and Notices - [Interim Results]"
    assert interim.language is None  # the parse decides
    assert interim.discovered_at == NOW
    announcement = interim.announcement
    assert announcement is not None
    assert announcement.publisher == "HKEXnews"
    assert announcement.announcement_id == "11910001"
    assert announcement.issuer_code == "03308"
    assert announcement.issuer_name == "ZJ INNOLIGHT"
    assert announcement.published_local == "21/08/2026 22:30"
    assert announcement.timezone == "Asia/Hong_Kong"
    assert announcement.file_type == "PDF"


def test_the_search_asks_for_the_stock_in_english_over_the_lookback() -> None:
    feed = Feed()

    run(feed, SearchQuery(since=datetime(2026, 7, 1, 0, 0, tzinfo=UTC)))

    (url,) = feed.requests
    assert url.startswith(f"{SEARCH}?")
    params = search_params(url)
    assert params["stockId"] == "1000311764"
    assert params["market"] == "SEHK"
    assert params["lang"] == "E"
    assert params["fromDate"] == "20260701"  # 08:00 in Hong Kong
    assert params["toDate"] == "20260929"
    assert params["rowRange"] == "100"
    assert params["sortByOptions"] == "DateTime"


def test_since_and_limit_bound_discovery() -> None:
    after_august = run(Feed(), SearchQuery(since=datetime(2026, 8, 1, tzinfo=UTC)))
    newest = run(Feed(), SearchQuery(limit=1))

    assert [c.announcement.announcement_id for c in after_august] == ["11920002", "11910001"]
    assert [c.announcement.announcement_id for c in newest] == ["11920002"]


def test_a_limit_is_the_row_range_asked_for() -> None:
    feed = Feed()

    run(feed, SearchQuery(limit=5))

    assert search_params(feed.requests[0])["rowRange"] == "5"


def envelope(rows: list[dict[str, str]], has_next: bool) -> bytes:
    return json.dumps(
        {"result": json.dumps(rows), "hasNextRow": has_next, "rowRange": 100, "lang": "E"}
    ).encode()


def fixture_rows() -> list[dict[str, str]]:
    return json.loads(json.loads((FIXTURES / "search.json").read_bytes())["result"])


def test_more_rows_are_asked_for_while_hkexnews_says_there_are_more() -> None:
    rows = fixture_rows()
    feed = Feed([envelope(rows[:1], True), envelope(rows, False)])

    candidates = run(feed, SearchQuery())

    assert [search_params(u)["rowRange"] for u in feed.requests] == ["100", "200"]
    assert len(candidates) == 3


def test_more_than_the_row_cap_fails_rather_than_dropping_announcements() -> None:
    feed = Feed([envelope(fixture_rows(), True)])

    with pytest.raises(FetchError, match="more than 500 announcements"):
        run(feed, SearchQuery())

    assert [search_params(u)["rowRange"] for u in feed.requests] == [
        "100",
        "200",
        "300",
        "400",
        "500",
    ]


def test_rows_that_are_not_documents_are_skipped() -> None:
    rows = fixture_rows()
    rows[0] = rows[0] | {"FILE_TYPE": "Multiple Files", "FILE_LINK": ""}

    candidates = run(Feed([envelope(rows, False)]), SearchQuery())

    assert [c.announcement.announcement_id for c in candidates] == ["11910001", "11890003"]


@pytest.mark.parametrize(
    "body",
    [b"<html>maintenance</html>", b'{"result": "{\\"not\\": \\"a list\\"}"}', b'{"result": 3}'],
)
def test_an_unexpected_search_answer_fails_discovery(body: bytes) -> None:
    with pytest.raises(FetchError, match="HKEXnews title search answered something unexpected"):
        run(Feed([body]), SearchQuery())


def test_an_empty_result_is_no_candidates() -> None:
    body = b'{"result": null, "hasNextRow": false, "rowRange": 100, "lang": "E"}'

    assert run(Feed([body]), SearchQuery()) == []


def test_fetch_returns_the_pdf_bytes_as_served() -> None:
    fetched = run(Feed(), SearchQuery(limit=3), fetch=True)

    interim = fetched[1]
    assert interim.url == f"{BASE}/0821/2026082101227.pdf"
    assert interim.media_type == "application/pdf"
    assert (
        interim.content
        == (FIXTURES / "listedco/listconews/sehk/2026/0821/2026082101227.pdf").read_bytes()
    )
    assert interim.not_modified is False
    assert interim.fetched_at == NOW
