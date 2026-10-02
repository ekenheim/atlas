"""Reading a running Atlas through its HTTP API, for the conformance check.

The check reads only through `/api/v1` (the same seam the owner and the frontend use), so it
runs alike against production (an `httpx2.Client` with the base URL) and against an in-process
app (FastAPI's `TestClient`). Both answer `get(url, params=...)` and `post(url, json=...)`.
"""

from collections.abc import Iterator, Mapping
from typing import Any, Protocol, cast

PAGE = 500  # the API's largest page


class _Response(Protocol):
    @property
    def status_code(self) -> int: ...

    @property
    def text(self) -> str: ...

    def json(self) -> Any: ...


class HttpClient(Protocol):
    """What the check needs of an HTTP client (`httpx2.Client`, FastAPI's `TestClient`)."""

    def get(self, url: str, *, params: Any = ...) -> Any: ...

    def post(self, url: str, *, json: Any = ...) -> Any: ...


class AtlasApiError(Exception):
    """An API request answered with an error status."""

    def __init__(self, method: str, path: str, status: int, body: str) -> None:
        super().__init__(f"{method} {path}: HTTP {status}: {body[:300]}")
        self.status = status


class AtlasApi:
    """`/api/v1` of a running Atlas, as JSON."""

    def __init__(self, client: HttpClient, prefix: str = "/api/v1") -> None:
        self._client = client
        self._prefix = prefix

    def get(self, path: str, **params: Any) -> Any:
        response = cast(_Response, self._client.get(self._prefix + path, params=params))
        return _json("GET", path, response)

    def text(self, path: str, **params: Any) -> str:
        response = cast(_Response, self._client.get(self._prefix + path, params=params))
        if response.status_code != 200:
            raise AtlasApiError("GET", path, response.status_code, response.text)
        return response.text

    def post(self, path: str, body: Mapping[str, Any]) -> Any:
        response = cast(_Response, self._client.post(self._prefix + path, json=dict(body)))
        return _json("POST", path, response)

    def pages(self, path: str, **params: Any) -> Iterator[dict[str, Any]]:
        """Every item of a paged listing."""
        offset = 0
        while True:
            page = self.get(path, limit=PAGE, offset=offset, **params)
            items = cast(list[dict[str, Any]], page["items"])
            yield from items
            offset += len(items)
            if not items or offset >= int(page["total"]):
                return

    def openapi(self) -> dict[str, Any]:
        """The app's OpenAPI schema (served at the root, not under the prefix)."""
        response = cast(_Response, self._client.get("/openapi.json", params={}))
        return cast(dict[str, Any], _json("GET", "/openapi.json", response))


def _json(method: str, path: str, response: _Response) -> Any:
    if response.status_code >= 300:
        raise AtlasApiError(method, path, response.status_code, response.text)
    return response.json()
