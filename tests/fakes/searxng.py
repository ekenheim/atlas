"""A transport-level fake SearXNG: `GET /search?q=...&format=json&engines=...`, scripted per query.

The responses are the hand-written fixtures in `tests/fixtures/searxng/` (no real SearXNG
response has been recorded; none may be requested from tests). Their shape follows SearXNG's
search API documentation (https://docs.searxng.org/dev/search_api.html) and its JSON output:
`query`, `number_of_results`, `results` (each with `url`, `title`, `content`, `engine`,
`engines`, `positions`, `score`, `category`, `publishedDate` (ISO 8601 or null) and the
template fields), `answers`, `corrections`, `infoboxes`, `suggestions` and
`unresponsive_engines`, a list of `[engine, reason]` pairs. The reasons used ("timeout",
"Suspended: access denied") are SearXNG's own messages for those failures.

A query answers only as scripted (`script`), in order per query: a fixture, an HTTP status
(`SearchReply.error`, e.g. 403 when the instance doesn't enable the JSON format, 429 from its
limiter) or a failed connection (`SearchReply.unreachable`). A query nobody scripted, or any
other endpoint, fails loudly, so the code under test can't search unplanned.
"""

import json
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import httpx2

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "searxng"


class UnexpectedSearch(AssertionError):
    """The code under test searched for something nobody scripted, or called another path."""


def fixture(name: str) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads((FIXTURES / f"{name}.json").read_text("utf-8")))


@dataclass(frozen=True)
class SearchReply:
    status: int = 200
    body: dict[str, Any] | None = None
    drop_connection: bool = False

    @classmethod
    def of(cls, name: str) -> "SearchReply":
        """The fixture `tests/fixtures/searxng/<name>.json`."""
        return cls(body=fixture(name))

    @classmethod
    def error(cls, status: int) -> "SearchReply":
        return cls(status=status)

    @classmethod
    def unreachable(cls) -> "SearchReply":
        return cls(drop_connection=True)


@dataclass
class FakeSearXNG:
    calls: list[httpx2.Request] = field(default_factory=list[httpx2.Request])
    replies: dict[str, deque[SearchReply]] = field(default_factory=dict[str, deque[SearchReply]])

    @property
    def transport(self) -> httpx2.MockTransport:
        return httpx2.MockTransport(self.handle)

    def script(self, query: str, *replies: SearchReply) -> "FakeSearXNG":
        """Answer the next searches for `query` with `replies`, in order."""
        self.replies.setdefault(query, deque()).extend(replies)
        return self

    def searches(self) -> list[dict[str, str]]:
        """The query parameters of every search received, oldest first."""
        return [dict(call.url.params) for call in self.calls]

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        self.calls.append(request)
        if (request.method, request.url.path) != ("GET", "/search"):
            raise UnexpectedSearch(f"{request.method} {request.url.path}")
        query = request.url.params.get("q", "")
        pending = self.replies.get(query)
        if not pending:
            raise UnexpectedSearch(f"search for {query!r} with no reply scripted")
        reply = pending.popleft()
        if reply.drop_connection:
            raise httpx2.ConnectError("connection refused", request=request)
        if reply.status != 200:
            return httpx2.Response(reply.status, text="<html>error</html>")
        return httpx2.Response(200, json=reply.body)
