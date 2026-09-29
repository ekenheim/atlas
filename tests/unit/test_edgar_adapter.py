"""The EDGAR adapter against recorded Lumentum responses (tests/fixtures/edgar/lumentum)."""

import hashlib
import math
from datetime import UTC, date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx2
import pytest

from atlas.sources import (
    EdgarAdapter,
    FetchError,
    FixtureReplay,
    SearchQuery,
    SecHttpClient,
    SourceAdapter,
    SourceCandidate,
    TokenBucket,
    fixture_edgar_adapter,
)

pytestmark = pytest.mark.anyio

FIXTURES = Path(__file__).parents[1] / "fixtures" / "edgar" / "lumentum"
LUMENTUM = "0001633978"
NOW = datetime(2026, 9, 28, 21, 0, tzinfo=UTC)
ARCHIVES = "https://www.sec.gov/Archives/edgar/data/1633978"
K8 = f"{ARCHIVES}/000162828026055726"
URL_8K = f"{K8}/lite-20260811.htm"
URL_EX991 = f"{K8}/lite_ex991xq4fy26.htm"
URL_10K = f"{ARCHIVES}/000162828026057358/lite-20260627.htm"
URL_10Q = f"{ARCHIVES}/000162828026030777/lite-20260328.htm"
URL_FACTS = "https://data.sec.gov/api/xbrl/companyfacts/CIK0001633978.json"


def adapter() -> EdgarAdapter:
    return fixture_edgar_adapter(FIXTURES, ciks=[LUMENTUM], now=lambda: NOW)


def by_url(candidates: list[SourceCandidate]) -> dict[str, SourceCandidate]:
    return {candidate.url: candidate for candidate in candidates}


def fixture_bytes(url: str) -> bytes:
    return (FIXTURES / url.split("://", 1)[1]).read_bytes()


async def test_discovers_target_filings_their_press_release_exhibit_and_companyfacts() -> None:
    source: SourceAdapter = adapter()

    candidates = await source.discover(SearchQuery(cik=LUMENTUM))

    # The fixture index also lists Form 4, 144, SD and 13G filings; only 10-K/10-Q/8-K count.
    assert [c.url for c in candidates] == [URL_10K, URL_8K, URL_EX991, URL_10Q, URL_FACTS]
    found = by_url(candidates)
    assert [found[u].document_type for u in (URL_10K, URL_8K, URL_EX991, URL_10Q)] == [
        "10-K",
        "8-K",
        "EX-99.1",
        "10-Q",
    ]
    assert found[URL_FACTS].kind == "sec_companyfacts"
    assert {c.provider_id for c in candidates} == {"sec_edgar"}
    assert {c.discovered_at for c in candidates} == {NOW}
    eight_k = found[URL_8K].filing
    assert eight_k is not None
    assert eight_k.accession_number == "0001628280-26-055726"
    assert eight_k.items == ("2.02", "9.01")
    assert found[URL_EX991].filing == eight_k


async def test_available_at_is_when_edgar_disseminated_each_filing() -> None:
    found = by_url(await adapter().discover(SearchQuery(cik=LUMENTUM)))

    accepted = {
        URL_10K: datetime(2026, 8, 17, 20, 3, 17, tzinfo=UTC),  # Monday 16:03 EDT
        URL_8K: datetime(2026, 8, 11, 20, 24, 11, tzinfo=UTC),  # Tuesday 16:24 EDT
        URL_EX991: datetime(2026, 8, 11, 20, 24, 11, tzinfo=UTC),
        URL_10Q: datetime(2026, 5, 5, 22, 3, 3, tzinfo=UTC),  # Tuesday 18:03 EDT
    }
    for url, acceptance in accepted.items():
        filing = found[url].filing
        assert filing is not None
        assert filing.acceptance_datetime == acceptance
    # Accepted within EDGAR's dissemination window: public at acceptance.
    for url in (URL_10K, URL_8K, URL_EX991):
        assert found[url].available_at == accepted[url]
        assert found[url].available_at_basis == "sec_acceptance"
    # Accepted after 17:30 ET: held until EDGAR opens the next business day, 06:00 EDT,
    # which is also the date EDGAR gave it as its filing date.
    assert found[URL_10Q].available_at == datetime(2026, 5, 6, 10, 0, tzinfo=UTC)
    assert found[URL_10Q].available_at_basis == "sec_dissemination"
    ten_q = found[URL_10Q].filing
    assert ten_q is not None and ten_q.filing_date == date(2026, 5, 6)

    # The submissions index's "Z" is real UTC: the 8-K's own SEC header records
    # <ACCEPTANCE-DATETIME>20260811162411 in Eastern time.
    assert accepted[URL_8K] == datetime(
        2026, 8, 11, 16, 24, 11, tzinfo=ZoneInfo("America/New_York")
    )
    # companyfacts has no acceptance time: it falls back to the observed discovery time.
    assert found[URL_FACTS].available_at == NOW
    assert found[URL_FACTS].available_at_basis == "observed_discovery"


async def test_fetch_returns_the_recorded_bytes_exactly() -> None:
    source = adapter()
    found = by_url(await source.discover(SearchQuery(cik=LUMENTUM)))

    for url in (URL_8K, URL_EX991, URL_10K, URL_10Q, URL_FACTS):
        document = await source.fetch(found[url])
        expected = fixture_bytes(url)
        assert hashlib.sha256(document.content).hexdigest() == hashlib.sha256(expected).hexdigest()
        assert document.not_modified is False
        assert document.fetched_at == NOW
        assert document.candidate == found[url]

    facts = await source.fetch(found[URL_FACTS])
    assert facts.media_type == "application/json"
    assert b'"entityName":"Lumentum Holdings Inc."' in facts.content  # raw, never parsed


async def test_refetching_with_the_last_validators_is_a_conditional_not_modified() -> None:
    source = adapter()
    eight_k = by_url(await source.discover(SearchQuery(cik=LUMENTUM)))[URL_8K]
    first = await source.fetch(eight_k)
    assert first.validators.last_modified == "Tue, 11 Aug 2026 20:24:36 GMT"

    again = await source.fetch(eight_k.model_copy(update={"validators": first.validators}))

    assert again.not_modified is True
    assert again.content == b""
    assert [a.status for a in again.attempts] == [304]


async def test_the_submissions_index_is_rechecked_conditionally() -> None:
    replay = FixtureReplay(FIXTURES)
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        response = replay(request)
        if request.url.path.startswith("/submissions/"):
            # data.sec.gov sends no validators today; if it ever does, use them.
            if request.headers.get("If-None-Match") == '"v1"':
                return httpx2.Response(304, headers={"ETag": '"v1"'})
            response.headers["ETag"] = '"v1"'
        return response

    source = EdgarAdapter(
        SecHttpClient(
            "Atlas Research test@example.com",
            transport=httpx2.MockTransport(handler),
            limiter=TokenBucket(rate_per_s=math.inf),
        ),
        ciks=[LUMENTUM],
        now=lambda: NOW,
    )

    first = await source.discover(SearchQuery(cik=LUMENTUM))
    second = await source.discover(SearchQuery(cik=LUMENTUM))

    submissions = [r for r in seen if r.url.path.startswith("/submissions/")]
    assert len(submissions) == 2
    assert "If-None-Match" not in submissions[0].headers
    assert submissions[1].headers["If-None-Match"] == '"v1"'
    assert second == first


async def test_updates_lists_only_filings_accepted_after_the_cursor() -> None:
    source = adapter()

    fresh = await source.updates(datetime(2026, 8, 11, 20, 24, 11, tzinfo=UTC))
    assert [c.url for c in fresh] == [URL_10K, URL_FACTS]

    since_july = await source.updates(datetime(2026, 7, 1, tzinfo=UTC))
    assert [c.url for c in since_july] == [URL_10K, URL_8K, URL_EX991, URL_FACTS]

    assert await source.updates(datetime(2026, 9, 1, tzinfo=UTC)) == []


async def test_discovery_can_be_narrowed_by_form_and_limit() -> None:
    candidates = await adapter().discover(SearchQuery(cik="1633978", forms=("10-Q",), limit=1))

    assert [c.url for c in candidates] == [URL_10Q, URL_FACTS]


async def test_every_request_to_the_replay_carries_the_user_agent() -> None:
    replay = FixtureReplay(FIXTURES)
    agents: list[str | None] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        agents.append(request.headers.get("User-Agent"))
        return replay(request)

    source = EdgarAdapter(
        SecHttpClient(
            "Atlas Research ops@example.com",
            transport=httpx2.MockTransport(handler),
            limiter=TokenBucket(rate_per_s=math.inf),
        ),
        ciks=[LUMENTUM],
    )
    for candidate in await source.discover(SearchQuery(cik=LUMENTUM)):
        await source.fetch(candidate)

    assert len(agents) == 7  # submissions, 8-K index headers, five documents
    assert set(agents) == {"Atlas Research ops@example.com"}


def test_the_replay_refuses_requests_without_a_user_agent_like_sec_does() -> None:
    response = FixtureReplay(FIXTURES)(httpx2.Request("GET", URL_8K, headers={"User-Agent": ""}))

    assert response.status_code == 403


async def test_a_429_from_sec_is_retried_through_the_adapter_and_recorded_on_the_document() -> None:
    replay = FixtureReplay(FIXTURES)
    throttled = {"remaining": 2}

    def handler(request: httpx2.Request) -> httpx2.Response:
        if str(request.url) == URL_8K and throttled["remaining"]:
            throttled["remaining"] -= 1
            return httpx2.Response(429, headers={"Retry-After": "2"})
        return replay(request)

    delays: list[float] = []

    async def sleep(seconds: float) -> None:
        delays.append(seconds)

    source = EdgarAdapter(
        SecHttpClient(
            "Atlas Research test@example.com",
            transport=httpx2.MockTransport(handler),
            limiter=TokenBucket(rate_per_s=math.inf),
            sleep=sleep,
        ),
        ciks=[LUMENTUM],
    )
    eight_k = by_url(await source.discover(SearchQuery(cik=LUMENTUM)))[URL_8K]

    document = await source.fetch(eight_k)

    assert document.content == fixture_bytes(URL_8K)
    assert delays == [2.0, 2.0]
    assert [(a.status, a.retry_after_s) for a in document.attempts] == [
        (429, 2.0),
        (429, 2.0),
        (200, None),
    ]


async def test_a_document_missing_from_sec_fails_without_retrying() -> None:
    source = adapter()
    eight_k = by_url(await source.discover(SearchQuery(cik=LUMENTUM)))[URL_8K]
    missing = eight_k.model_copy(update={"url": f"{K8}/no-such-document.htm"})

    with pytest.raises(FetchError) as raised:
        await source.fetch(missing)

    assert raised.value.status == 404
    assert raised.value.retryable is False
    assert len(raised.value.attempts) == 1


# --- 8-K selection for bottleneck relevance ---

RELEVANT_8K_ITEMS = ("1.01", "1.02", "2.01", "2.02", "2.05", "7.01", "8.01")
PRESS_RELEASE_ITEMS = ("2.02", "7.01", "8.01", "9.01")


def fixtures_with_8k_items(tmp_path: Path, items: str) -> Path:
    """A copy of the fixtures whose one 8-K lists `items` instead of 2.02,9.01."""
    import json
    import shutil

    root = tmp_path / "lumentum"
    shutil.copytree(FIXTURES, root)
    path = root / "data.sec.gov" / "submissions" / "CIK0001633978.json"
    index = json.loads(path.read_text())
    recent = index["filings"]["recent"]
    for i, accession in enumerate(recent["accessionNumber"]):
        if accession == "0001628280-26-055726":
            recent["items"][i] = items
    path.write_text(json.dumps(index))
    return root


def selecting_adapter(root: Path) -> EdgarAdapter:
    return fixture_edgar_adapter(
        root,
        ciks=[LUMENTUM],
        now=lambda: NOW,
        eight_k_items=RELEVANT_8K_ITEMS,
        exhibits_only_items=PRESS_RELEASE_ITEMS,
    )


async def test_a_press_release_8k_contributes_only_its_exhibits() -> None:
    candidates = await selecting_adapter(FIXTURES).discover(SearchQuery(cik=LUMENTUM))

    urls = [c.url for c in candidates]
    assert URL_EX991 in urls  # items 2.02,9.01: the earnings release is the substance
    assert URL_8K not in urls  # the cover document is boilerplate


async def test_an_8k_with_only_governance_items_is_not_discovered(tmp_path: Path) -> None:
    root = fixtures_with_8k_items(tmp_path, "5.02,5.07")

    urls = [c.url for c in await selecting_adapter(root).discover(SearchQuery(cik=LUMENTUM))]

    assert URL_8K not in urls and URL_EX991 not in urls
    assert URL_10K in urls and URL_10Q in urls  # periodic reports are unaffected


async def test_a_material_agreement_8k_keeps_its_body_and_exhibits(tmp_path: Path) -> None:
    root = fixtures_with_8k_items(tmp_path, "1.01,9.01")

    urls = [c.url for c in await selecting_adapter(root).discover(SearchQuery(cik=LUMENTUM))]

    assert URL_8K in urls and URL_EX991 in urls  # an agreement's terms are in the body


async def test_without_selection_every_8k_and_its_cover_are_discovered() -> None:
    urls = [c.url for c in await adapter().discover(SearchQuery(cik=LUMENTUM))]

    assert URL_8K in urls and URL_EX991 in urls
