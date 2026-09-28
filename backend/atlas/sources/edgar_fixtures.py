"""Replay recorded EDGAR responses: the fixture EDGAR adapter.

A fixture directory holds `manifest.json` (each recorded URL with its status, headers and
body file) and the bodies under paths mirroring the URLs, e.g.
`www.sec.gov/Archives/edgar/data/1633978/.../lite-20260811.htm`. The replay behaves like
SEC where it matters: a request without a User-Agent is refused (403), an unrecorded URL is
404, and a conditional request whose validators still match gets a 304.
"""

import math
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path

import httpx2
from pydantic import BaseModel

from atlas.sources.edgar import EdgarAdapter
from atlas.sources.sec_http import SecHttpClient, TokenBucket

FIXTURE_USER_AGENT = "Atlas Research fixture-replay@example.invalid"


class _RecordedResponse(BaseModel):
    url: str
    file: str
    status: int = 200
    headers: dict[str, str] = {}
    trimmed: str | None = None  # how a large body was cut down, if it was


class _Manifest(BaseModel):
    responses: list[_RecordedResponse]


def _not_modified_since(last_modified: str | None, if_modified_since: str | None) -> bool:
    if not last_modified or not if_modified_since:
        return False
    try:
        return parsedate_to_datetime(last_modified) <= parsedate_to_datetime(if_modified_since)
    except (TypeError, ValueError):
        return False


class FixtureReplay:
    """An httpx2 request handler serving the responses recorded in a fixture directory."""

    def __init__(self, root: Path) -> None:
        self._root = root
        manifest = _Manifest.model_validate_json((root / "manifest.json").read_bytes())
        self._responses = {recorded.url: recorded for recorded in manifest.responses}

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        if not request.headers.get("User-Agent", "").strip():
            return httpx2.Response(403, text="Request originates from an undeclared tool")
        recorded = self._responses.get(str(request.url))
        if recorded is None:
            return httpx2.Response(404, text=f"not recorded: {request.url}")
        headers = {name.lower(): value for name, value in recorded.headers.items()}
        etag, last_modified = headers.get("etag"), headers.get("last-modified")
        if_none_match = request.headers.get("If-None-Match")
        unchanged = (
            etag == if_none_match
            if etag and if_none_match
            else _not_modified_since(last_modified, request.headers.get("If-Modified-Since"))
        )
        if unchanged:
            kept = {k: v for k, v in headers.items() if k in {"etag", "last-modified"}}
            return httpx2.Response(304, headers=kept)
        body = (self._root / recorded.file).read_bytes()
        return httpx2.Response(recorded.status, headers=headers, content=body)

    def transport(self) -> httpx2.MockTransport:
        return httpx2.MockTransport(self)


def fixture_edgar_adapter(
    root: Path,
    *,
    ciks: Sequence[str],
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    user_agent: str = FIXTURE_USER_AGENT,
) -> EdgarAdapter:
    """The EDGAR adapter over recorded responses. Replays are local, so they skip the
    process-wide SEC rate limiter (which exists to protect SEC)."""
    client = SecHttpClient(
        user_agent,
        transport=FixtureReplay(root).transport(),
        limiter=TokenBucket(rate_per_s=math.inf),
    )
    return EdgarAdapter(client, ciks=ciks, now=now)
