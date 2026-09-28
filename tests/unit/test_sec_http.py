"""The SEC HTTP client at the transport boundary: retries, conditional requests, User-Agent,
and the process-wide rate limit. SEC is replaced by an httpx2 MockTransport."""

import asyncio
import math
import time
from collections.abc import Callable

import httpx2
import pytest

from atlas.sources import FetchError, HttpValidators, SecHttpClient, TokenBucket

pytestmark = pytest.mark.anyio

UA = "Atlas Research test@example.com"
URL = "https://www.sec.gov/Archives/edgar/data/1633978/000162828026055726/lite-20260811.htm"
Handler = Callable[[httpx2.Request], httpx2.Response]


class FakeSleep:
    """Records requested delays instead of sleeping."""

    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.delays.append(seconds)


def client(
    handler: Handler,
    sleep: FakeSleep | None = None,
    *,
    max_attempts: int = 5,
    backoff_base_s: float = 1.0,
    max_retry_after_s: float = 600.0,
) -> SecHttpClient:
    return SecHttpClient(
        UA,
        transport=httpx2.MockTransport(handler),
        limiter=TokenBucket(rate_per_s=math.inf),
        sleep=sleep or FakeSleep(),
        max_attempts=max_attempts,
        backoff_base_s=backoff_base_s,
        max_retry_after_s=max_retry_after_s,
    )


def sequence(*responses: httpx2.Response | Exception) -> tuple[Handler, list[httpx2.Request]]:
    seen: list[httpx2.Request] = []
    pending = list(responses)

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        item = pending.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    return handler, seen


async def test_429_honors_retry_after_records_attempts_and_eventually_succeeds() -> None:
    handler, seen = sequence(
        httpx2.Response(429, headers={"Retry-After": "7"}),
        httpx2.Response(429, headers={"Retry-After": "3"}),
        httpx2.Response(200, content=b"<html>8-K</html>", headers={"Content-Type": "text/html"}),
    )
    sleep = FakeSleep()

    async with client(handler, sleep) as sec:
        result = await sec.get(URL)

    assert result.content == b"<html>8-K</html>"
    assert result.media_type == "text/html"
    assert len(seen) == 3
    assert sleep.delays == [7.0, 3.0]
    assert [(a.attempt, a.status, a.retry_after_s, a.delay_s) for a in result.attempts] == [
        (1, 429, 7.0, 7.0),
        (2, 429, 3.0, 3.0),
        (3, 200, None, None),
    ]


async def test_retry_after_as_an_http_date_is_honored() -> None:
    handler, _ = sequence(
        httpx2.Response(429, headers={"Retry-After": "Wed, 21 Oct 2037 07:28:00 GMT"}),
        httpx2.Response(200, content=b"ok"),
    )
    sleep = FakeSleep()

    async with client(handler, sleep, max_retry_after_s=math.inf) as sec:
        await sec.get(URL)

    # Far in the future, so the delay is large: taken from the date, not the backoff.
    assert sleep.delays[0] > 300 * 24 * 3600


async def test_server_errors_and_timeouts_are_retried_with_exponential_backoff() -> None:
    request = httpx2.Request("GET", URL)
    handler, seen = sequence(
        httpx2.Response(503),
        httpx2.ReadTimeout("timed out", request=request),
        httpx2.Response(500),
        httpx2.Response(200, content=b"ok"),
    )
    sleep = FakeSleep()

    async with client(handler, sleep, backoff_base_s=0.5) as sec:
        result = await sec.get(URL)

    assert result.content == b"ok"
    assert len(seen) == 4
    assert sleep.delays == [0.5, 1.0, 2.0]
    assert [a.status for a in result.attempts] == [503, None, 500, 200]
    assert result.attempts[1].error is not None and "ReadTimeout" in result.attempts[1].error


@pytest.mark.parametrize("status", [400, 403, 404])
async def test_other_client_errors_are_not_retried(status: int) -> None:
    handler, seen = sequence(httpx2.Response(status))
    sleep = FakeSleep()

    async with client(handler, sleep) as sec:
        with pytest.raises(FetchError) as raised:
            await sec.get(URL)

    assert len(seen) == 1
    assert sleep.delays == []
    assert raised.value.status == status
    assert raised.value.retryable is False
    assert [a.status for a in raised.value.attempts] == [status]


async def test_gives_up_after_the_attempt_budget_with_every_attempt_recorded() -> None:
    handler, seen = sequence(*[httpx2.Response(503) for _ in range(3)])

    async with client(handler, max_attempts=3) as sec:
        with pytest.raises(FetchError) as raised:
            await sec.get(URL)

    assert len(seen) == 3
    assert raised.value.retryable is True
    assert [a.attempt for a in raised.value.attempts] == [1, 2, 3]


async def test_a_retry_after_beyond_the_cap_fails_fast_instead_of_blocking() -> None:
    handler, seen = sequence(httpx2.Response(429, headers={"Retry-After": "3600"}))
    sleep = FakeSleep()

    async with client(handler, sleep, max_retry_after_s=600) as sec:
        with pytest.raises(FetchError) as raised:
            await sec.get(URL)

    assert len(seen) == 1
    assert sleep.delays == []
    assert raised.value.retryable is True
    assert raised.value.attempts[0].retry_after_s == 3600.0


async def test_conditional_request_sends_validators_and_reports_not_modified() -> None:
    handler, seen = sequence(
        httpx2.Response(
            200,
            content=b"v1",
            headers={"ETag": '"abc"', "Last-Modified": "Tue, 11 Aug 2026 20:24:36 GMT"},
        ),
        httpx2.Response(304),
    )

    async with client(handler) as sec:
        first = await sec.get(URL)
        second = await sec.get(URL, validators=first.validators)

    assert first.validators == HttpValidators(
        etag='"abc"', last_modified="Tue, 11 Aug 2026 20:24:36 GMT"
    )
    assert "if-none-match" not in seen[0].headers
    assert seen[1].headers["If-None-Match"] == '"abc"'
    assert seen[1].headers["If-Modified-Since"] == "Tue, 11 Aug 2026 20:24:36 GMT"
    assert second.not_modified is True
    assert second.content == b""
    assert second.validators == first.validators  # carried over when a 304 omits them


async def test_every_request_carries_the_configured_user_agent() -> None:
    handler, seen = sequence(httpx2.Response(503), httpx2.Response(200), httpx2.Response(200))

    async with client(handler) as sec:
        await sec.get(URL)
        await sec.get("https://data.sec.gov/submissions/CIK0001633978.json")

    assert [request.headers["User-Agent"] for request in seen] == [UA, UA, UA]


@pytest.mark.parametrize("user_agent", ["", "   ", "Atlas Research"])
def test_a_user_agent_without_a_contact_email_is_refused(user_agent: str) -> None:
    with pytest.raises(ValueError, match="User-Agent"):
        SecHttpClient(user_agent, transport=httpx2.MockTransport(lambda r: httpx2.Response(200)))


async def test_clients_share_one_process_wide_limit_of_ten_requests_per_second() -> None:
    """Two clients (as two concurrent jobs would) built with the default limiter."""
    stamps: list[float] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        stamps.append(time.monotonic())
        return httpx2.Response(200)

    job_a = SecHttpClient(UA, transport=httpx2.MockTransport(handler))
    job_b = SecHttpClient(UA, transport=httpx2.MockTransport(handler))
    async with job_a, job_b:
        await asyncio.gather(*(job.get(f"{URL}?n={n}") for n in range(8) for job in (job_a, job_b)))

    assert len(stamps) == 16
    stamps.sort()
    # No window of one second ever holds more than ten requests (1 ms timer slack).
    for first, eleventh in zip(stamps, stamps[10:], strict=False):
        assert eleventh - first >= 1.0 - 1e-3
