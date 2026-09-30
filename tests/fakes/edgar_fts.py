"""A transport-level fake of SEC EDGAR full-text search: `GET …/search-index?q=...`, scripted
per `q`.

The answers are the fixtures in `tests/fixtures/edgar-fts/` (see its manifest: one recorded
on 2026-09-30 and trimmed, one hand-written empty answer). A `q` answers only as scripted
(`script`), in order: a fixture (`FilingReply.of`), an HTTP status (`FilingReply.error`) or a
failed connection (`FilingReply.unreachable`). An unscripted `q`, or any other path, fails
loudly, so the code under test can't search unplanned. The fake serves the real host through
an `httpx2.MockTransport` and a localhost URL through `tests/fakes/serve.py`.
"""

import json
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import httpx2

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "edgar-fts"


class UnexpectedFilingSearch(AssertionError):
    """The code under test searched for something nobody scripted, or called another path."""


def fixture(name: str) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads((FIXTURES / f"{name}.json").read_text("utf-8")))


@dataclass(frozen=True)
class FilingReply:
    status: int = 200
    body: dict[str, Any] | None = None
    drop_connection: bool = False

    @classmethod
    def of(cls, name: str) -> "FilingReply":
        """The fixture `tests/fixtures/edgar-fts/<name>.json`."""
        return cls(body=fixture(name))

    @classmethod
    def error(cls, status: int) -> "FilingReply":
        return cls(status=status)

    @classmethod
    def unreachable(cls) -> "FilingReply":
        return cls(drop_connection=True)


@dataclass
class FakeEdgarFullTextSearch:
    calls: list[httpx2.Request] = field(default_factory=list[httpx2.Request])
    replies: dict[str, deque[FilingReply]] = field(default_factory=dict[str, deque[FilingReply]])

    @property
    def transport(self) -> httpx2.MockTransport:
        return httpx2.MockTransport(self.handle)

    def script(self, q: str, *replies: FilingReply) -> "FakeEdgarFullTextSearch":
        """Answer the next searches whose `q` is `q` with `replies`, in order."""
        self.replies.setdefault(q, deque()).extend(replies)
        return self

    def searches(self) -> list[dict[str, str]]:
        """The query parameters of every search received, oldest first."""
        return [dict(call.url.params) for call in self.calls]

    def user_agents(self) -> list[str | None]:
        return [call.headers.get("User-Agent") for call in self.calls]

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        self.calls.append(request)
        if request.method != "GET" or not request.url.path.endswith("/search-index"):
            raise UnexpectedFilingSearch(f"{request.method} {request.url.path}")
        q = request.url.params.get("q", "")
        pending = self.replies.get(q)
        if not pending:
            raise UnexpectedFilingSearch(f"EDGAR full-text search for {q!r} with no reply scripted")
        reply = pending.popleft()
        if reply.drop_connection:
            raise httpx2.ConnectError("connection refused", request=request)
        if reply.status != 200:
            return httpx2.Response(reply.status, text="<html>error</html>")
        return httpx2.Response(200, json=reply.body)
