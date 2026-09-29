"""A polite synchronous JSON client shared by the identity sources (SEC, GLEIF, OpenFIGI).

- Each source has its own rate limiter (a `TokenBucket`, no bursts), passed in.
- 429 and 5xx are retried with exponential backoff, honouring `Retry-After` or OpenFIGI's
  `ratelimit-reset` (seconds); timeouts and network errors are retried too. Other 4xx fail.
- Every failure is an `IdentitySourceError` naming the source.

The transport is injectable: tests replace every provider with an httpx2 MockTransport.
"""

import time
from collections.abc import Callable
from typing import Any, Self

import httpx2

from atlas.sources.sec_http import TokenBucket

Sleep = Callable[[float], None]


class IdentitySourceError(Exception):
    """An identity source failed; the message names the source and why."""

    def __init__(self, source: str, message: str, *, status: int | None = None) -> None:
        super().__init__(f"{source}: {message}")
        self.source = source
        self.status = status


def _wait_seconds(response: httpx2.Response) -> float | None:
    for header in ("Retry-After", "ratelimit-reset"):
        value = response.headers.get(header)
        if value is not None and value.strip().isdigit():
            return float(value.strip())
    return None


class JsonHttp:
    def __init__(
        self,
        source: str,
        *,
        limiter: TokenBucket,
        headers: dict[str, str] | None = None,
        transport: httpx2.BaseTransport | None = None,
        sleep: Sleep = time.sleep,
        max_attempts: int = 4,
        backoff_base_s: float = 2.0,
        max_wait_s: float = 120.0,
        timeout_s: float = 30.0,
    ) -> None:
        self.source = source
        self._limiter = limiter
        self._sleep = sleep
        self._max_attempts = max_attempts
        self._backoff_base_s = backoff_base_s
        self._max_wait_s = max_wait_s
        self._client = httpx2.Client(
            transport=transport, headers=headers or {}, timeout=timeout_s, follow_redirects=True
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, str] | None = None,
        json: Any = None,
        missing_ok: bool = False,
    ) -> bytes | None:
        """The response body (JSON, parsed by the caller); None for a 404 when `missing_ok`."""
        for attempt in range(1, self._max_attempts + 1):
            self._limiter.wait(self._sleep)
            wait: float | None = None
            try:
                response = self._client.request(method, url, params=params, json=json)
            except httpx2.TransportError as error:
                failure = f"{type(error).__name__}: {error}"
            else:
                if response.status_code == 404 and missing_ok:
                    return None
                if response.is_success:
                    return response.content
                failure = f"HTTP {response.status_code}"
                if response.status_code != 429 and response.status_code < 500:
                    raise IdentitySourceError(
                        self.source,
                        f"{method} {url}: {failure}: {response.text[:200]}",
                        status=response.status_code,
                    )
                wait = _wait_seconds(response)
            delay = wait if wait is not None else self._backoff_base_s * 2 ** (attempt - 1)
            if attempt == self._max_attempts or delay > self._max_wait_s:
                raise IdentitySourceError(
                    self.source, f"{method} {url}: gave up after {attempt} attempts ({failure})"
                )
            self._sleep(delay)
        raise AssertionError("unreachable")  # pragma: no cover
