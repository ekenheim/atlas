"""The SearXNG client at its transport boundary, and the canonical URL that dedupes leads.

SearXNG is the scripted fake (`tests/fakes/searxng.py`) over the hand-written fixtures in
`tests/fixtures/searxng/`, in the documented JSON shape.
"""

from datetime import date
from pathlib import Path

import pytest

from atlas.discovery import SearchFailed, SearXNGClient, canonical_url
from tests.fakes.searxng import FakeSearXNG, SearchReply
from tests.harness import make_settings

SUBSTRATE = "indium phosphide substrate capacity expansion 2026"
SECOND_SOURCE = "InP laser second source qualification hyperscaler"
NOTHING = "electro-absorption modulated laser shortage 800G transceivers"


def client(fake: FakeSearXNG, **values: object) -> SearXNGClient:
    settings = make_settings(Path("/tmp/unused"), searxng_url="http://searxng.test/", **values)
    searxng = SearXNGClient.from_settings(settings, transport=fake.transport)
    assert searxng is not None
    return searxng


def test_a_search_names_its_engines_and_asks_for_json() -> None:
    fake = FakeSearXNG().script(SUBSTRATE, SearchReply.of("inp-substrate-capacity"))

    client(fake).search(SUBSTRATE)

    [call] = fake.calls
    assert (call.method, call.url.host, call.url.path) == ("GET", "searxng.test", "/search")
    assert fake.searches() == [{"q": SUBSTRATE, "format": "json", "engines": "bing,brave"}]


def test_the_engines_are_config() -> None:
    fake = FakeSearXNG().script(SUBSTRATE, SearchReply.of("inp-substrate-capacity"))

    client(fake, searxng_engines="brave, mojeek").search(SUBSTRATE)

    assert fake.searches()[0]["engines"] == "brave,mojeek"


def test_results_keep_url_title_snippet_engines_and_published_date() -> None:
    fake = FakeSearXNG().script(SUBSTRATE, SearchReply.of("inp-substrate-capacity"))

    response = client(fake).search(SUBSTRATE)

    assert response.query == SUBSTRATE
    first, second, third = response.results
    assert first.url == (
        "https://www.photonics-news.test/2026/08/axt-expands-inp-substrate-capacity"
        "?utm_source=rss&utm_medium=feed"
    )
    assert first.title == "AXT expands indium phosphide substrate capacity in Beijing"
    assert first.snippet.startswith("AXT said it would add InP substrate capacity")
    assert first.engines == ["bing", "brave"]
    assert first.published_date == date(2026, 8, 12)
    assert first.position == 1
    assert (second.published_date, second.engines, second.position) == (None, ["bing"], 2)
    assert third.url == "ftp://files.photonics-news.test/inp-report.pdf"
    assert response.unresponsive_engines == []


def test_unresponsive_engines_are_recorded_with_their_reasons() -> None:
    fake = FakeSearXNG().script(NOTHING, SearchReply.of("no-results"))

    response = client(fake).search(NOTHING)

    assert response.results == []
    assert [(e.engine, e.reason) for e in response.unresponsive_engines] == [
        ("bing", "Suspended: access denied"),
        ("brave", "timeout"),
    ]


def test_a_date_only_published_date_is_read() -> None:
    fake = FakeSearXNG().script(SECOND_SOURCE, SearchReply.of("inp-laser-second-source"))

    response = client(fake).search(SECOND_SOURCE)

    assert [r.published_date for r in response.results] == [date(2026, 8, 13), date(2026, 7, 1)]


@pytest.mark.parametrize(
    ("reply", "message"),
    [
        (SearchReply.error(403), "HTTP 403"),  # the instance doesn't enable format=json
        (SearchReply.error(429), "HTTP 429"),  # its limiter
        (SearchReply.error(502), "HTTP 502"),
        (SearchReply.unreachable(), "ConnectError"),
    ],
)
def test_a_failed_search_raises_search_failed(reply: SearchReply, message: str) -> None:
    fake = FakeSearXNG().script(SUBSTRATE, reply)

    with pytest.raises(SearchFailed, match=message):
        client(fake).search(SUBSTRATE)


def test_a_response_that_isn_t_searxng_json_raises_search_failed() -> None:
    fake = FakeSearXNG().script(SUBSTRATE, SearchReply(body={"results": "nope"}))

    with pytest.raises(SearchFailed, match="unexpected response"):
        client(fake).search(SUBSTRATE)


def test_no_client_without_a_searxng_url() -> None:
    assert SearXNGClient.from_settings(make_settings(Path("/tmp/unused"))) is None


@pytest.mark.parametrize(
    ("url", "canonical"),
    [
        (
            "https://www.photonics-news.test/2026/08/axt?utm_source=rss&utm_medium=feed",
            "https://photonics-news.test/2026/08/axt",
        ),
        (
            "https://PHOTONICS-NEWS.test:443/2026/08/axt/#comments",
            "https://photonics-news.test/2026/08/axt",
        ),
        (
            "https://blog.photonics.test/post/?utm_campaign=feed&b=2&a=1",
            "https://blog.photonics.test/post?a=1&b=2",
        ),
        ("http://example.test:80", "http://example.test/"),
        ("http://example.test:8080/a", "http://example.test:8080/a"),
        ("https://example.test/a?gclid=1&fbclid=2&id=7", "https://example.test/a?id=7"),
        ("https://example.test/A/b", "https://example.test/A/b"),  # paths keep their case
    ],
)
def test_canonical_urls(url: str, canonical: str) -> None:
    assert canonical_url(url) == canonical


@pytest.mark.parametrize("url", ["ftp://example.test/x", "mailto:a@example.test", "not a url"])
def test_only_web_urls_have_a_canonical_url(url: str) -> None:
    assert canonical_url(url) is None
