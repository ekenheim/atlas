"""A polite HTTP client for SEC endpoints (SEC fair-access policy).

- Every request carries the configured User-Agent (a name and a contact email).
- All SEC traffic in the process shares one rate limiter, `SEC_RATE_LIMITER` (10 req/s).
- 429, 5xx, timeouts and network errors are retried with exponential backoff, honoring
  Retry-After; other 4xx fail at once. Every attempt is recorded.
- Conditional requests: callers pass the validators from their last fetch, and a 304 comes
  back as `not_modified`.

The transport is injectable, so tests replace SEC with an httpx2 MockTransport.
"""

import asyncio
import re
import threading
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from types import TracebackType
from typing import Self

import httpx2

from atlas.sources.adapter import FetchAttempt, FetchError, HttpValidators

Sleep = Callable[[float], Awaitable[None]]

_CONTACT_EMAIL = re.compile(r"\S+@\S+\.\S+")


class TokenBucket:
    """A token bucket holding one token, refilled at `rate_per_s`.

    With a capacity of one there are no bursts: grants are spaced at least `1 / rate_per_s`
    apart, so no one-second window ever holds more than `rate_per_s` requests. Slots are
    reserved under a thread lock, so one instance is safe to share across every event loop
    and thread in the process.
    """

    def __init__(self, rate_per_s: float, *, clock: Callable[[], float] = time.monotonic) -> None:
        if rate_per_s <= 0:
            raise ValueError("rate_per_s must be positive")
        self._interval = 1.0 / rate_per_s
        self._clock = clock
        self._next_slot = float("-inf")
        self._lock = threading.Lock()

    def _reserve(self) -> float:
        with self._lock:
            now = self._clock()
            slot = max(now, self._next_slot)
            self._next_slot = slot + self._interval
            return slot - now

    async def acquire(self) -> None:
        delay = self._reserve()
        if delay > 0:
            await asyncio.sleep(delay)


# The one limiter for all SEC traffic in this process (SEC allows at most 10 requests/s).
SEC_RATE_LIMITER = TokenBucket(rate_per_s=10)


@dataclass(frozen=True, slots=True)
class HttpResult:
    url: str
    status: int
    not_modified: bool
    content: bytes
    media_type: str | None
    validators: HttpValidators
    attempts: tuple[FetchAttempt, ...]


def _retry_after_seconds(value: str | None) -> float | None:
    """Retry-After is either delta-seconds or an HTTP-date."""
    if value is None:
        return None
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max(0.0, (when - datetime.now(UTC)).total_seconds())


def _is_retryable(status: int) -> bool:
    return status == 429 or status >= 500


class SecHttpClient:
    def __init__(
        self,
        user_agent: str,
        *,
        transport: httpx2.AsyncBaseTransport | None = None,
        limiter: TokenBucket = SEC_RATE_LIMITER,
        sleep: Sleep = asyncio.sleep,
        max_attempts: int = 5,
        backoff_base_s: float = 1.0,
        backoff_max_s: float = 60.0,
        max_retry_after_s: float = 600.0,
        timeout_s: float = 30.0,
    ) -> None:
        user_agent = user_agent.strip()
        if not _CONTACT_EMAIL.search(user_agent):
            raise ValueError(
                "SEC User-Agent must name the requester and include a contact email, "
                "e.g. 'Atlas Research ops@example.com'"
            )
        self._limiter = limiter
        self._sleep = sleep
        self._max_attempts = max_attempts
        self._backoff_base_s = backoff_base_s
        self._backoff_max_s = backoff_max_s
        self._max_retry_after_s = max_retry_after_s
        self._client = httpx2.AsyncClient(
            transport=transport,
            headers={"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"},
            timeout=timeout_s,
            follow_redirects=True,
        )

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def get(self, url: str, validators: HttpValidators | None = None) -> HttpResult:
        headers: dict[str, str] = {}
        if validators and validators.etag:
            headers["If-None-Match"] = validators.etag
        if validators and validators.last_modified:
            headers["If-Modified-Since"] = validators.last_modified

        attempts: list[FetchAttempt] = []
        for attempt in range(1, self._max_attempts + 1):
            await self._limiter.acquire()
            status: int | None = None
            error: str | None = None
            retry_after: float | None = None
            try:
                response = await self._client.get(url, headers=headers)
            except (httpx2.TimeoutException, httpx2.NetworkError, httpx2.RemoteProtocolError) as e:
                error = f"{type(e).__name__}: {e}"
            except httpx2.HTTPError as e:
                attempts.append(FetchAttempt(attempt=attempt, error=f"{type(e).__name__}: {e}"))
                raise FetchError(
                    f"GET {url} failed: {e}",
                    url=url,
                    status=None,
                    retryable=False,
                    attempts=tuple(attempts),
                ) from e
            else:
                status = response.status_code
                if status < 400:
                    attempts.append(FetchAttempt(attempt=attempt, status=status))
                    return self._result(response, validators, tuple(attempts))
                if not _is_retryable(status):
                    attempts.append(FetchAttempt(attempt=attempt, status=status))
                    raise FetchError(
                        f"GET {url} returned {status}",
                        url=url,
                        status=status,
                        retryable=False,
                        attempts=tuple(attempts),
                    )
                retry_after = _retry_after_seconds(response.headers.get("Retry-After"))

            delay = (
                retry_after
                if retry_after is not None
                else min(self._backoff_max_s, self._backoff_base_s * 2 ** (attempt - 1))
            )
            if attempt == self._max_attempts or delay > self._max_retry_after_s:
                attempts.append(
                    FetchAttempt(
                        attempt=attempt, status=status, error=error, retry_after_s=retry_after
                    )
                )
                if attempt == self._max_attempts:
                    reason = f"gave up after {attempt} attempts"
                else:
                    cap = self._max_retry_after_s
                    reason = f"server asked to wait {delay:.0f}s, beyond the {cap:.0f}s cap"
                raise FetchError(
                    f"GET {url}: {reason} (last: {status or error})",
                    url=url,
                    status=status,
                    retryable=True,
                    attempts=tuple(attempts),
                )
            attempts.append(
                FetchAttempt(
                    attempt=attempt,
                    status=status,
                    error=error,
                    retry_after_s=retry_after,
                    delay_s=delay,
                )
            )
            await self._sleep(delay)
        raise AssertionError("unreachable: the loop returns or raises")  # pragma: no cover

    @staticmethod
    def _result(
        response: httpx2.Response,
        sent: HttpValidators | None,
        attempts: tuple[FetchAttempt, ...],
    ) -> HttpResult:
        not_modified = response.status_code == 304
        validators = HttpValidators(
            etag=response.headers.get("ETag"), last_modified=response.headers.get("Last-Modified")
        )
        if not_modified and sent is not None:
            # A 304 may omit the validators; the ones we sent are still current.
            validators = HttpValidators(
                etag=validators.etag or sent.etag,
                last_modified=validators.last_modified or sent.last_modified,
            )
        content_type = response.headers.get("Content-Type")
        return HttpResult(
            url=str(response.url),
            status=response.status_code,
            not_modified=not_modified,
            content=b"" if not_modified else response.content,
            media_type=content_type.split(";", 1)[0].strip() if content_type else None,
            validators=validators,
            attempts=attempts,
        )
