"""The routes a tool wraps: Atlas's own `/api/v1`, called in process through the ASGI transport
(the same handlers, validation and error envelope as any client; nothing is re-implemented).

A 4xx answer is a `Refusal` (the route's code and message), a 5xx or an exception a `Failed`.
"""

import json
from typing import Any, Self, cast

import httpx2


class Refusal(Exception):
    """Atlas refused the call (a rule of the MCP layer, or the route's own 4xx)."""

    def __init__(self, code: str, message: str, **detail: Any) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.detail = detail


class Failed(Exception):
    """The call failed on Atlas's side (a 5xx, an unreachable dependency)."""

    def __init__(self, code: str, message: str, **detail: Any) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.detail = detail


class Api:
    """One tool call's view of the routes."""

    def __init__(self, app: Any) -> None:
        self._client = httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app), base_url="http://atlas.internal"
        )

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self._client.aclose()

    async def get(self, path: str, **params: Any) -> dict[str, Any]:
        query = {key: value for key, value in params.items() if value is not None}
        return _json(await self._client.get("/api/v1" + path, params=query))

    async def get_text(self, path: str, **params: Any) -> str:
        query = {key: value for key, value in params.items() if value is not None}
        response = await self._client.get("/api/v1" + path, params=query)
        _check(response)
        return response.content.decode("utf-8")  # the archive's parsed text is UTF-8

    async def post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        return _json(await self._client.post("/api/v1" + path, json=body))


def rows(value: Any) -> list[dict[str, Any]]:
    """A list of JSON objects from an answer's field (missing or null: empty)."""
    return cast(list[dict[str, Any]], value or [])


def obj(value: Any) -> dict[str, Any]:
    """A JSON object from an answer's field (missing or null: empty)."""
    return cast(dict[str, Any], value or {})


def _check(response: httpx2.Response) -> None:
    if response.is_success:
        return
    code, message = f"http_{response.status_code}", response.text[:300]
    detail: dict[str, Any] = {}
    try:
        error = cast(dict[str, Any], cast(dict[str, Any], response.json()).get("error") or {})
        code, message = str(error.get("code", code)), str(error.get("message", message))
        detail = obj(error.get("detail"))  # what the refusal adds (a judge's `beyond`, ...)
    except (ValueError, AttributeError):
        pass
    if response.status_code < 500:
        raise Refusal(code, message, **detail, http=response.status_code)
    raise Failed(code, message, **detail, http=response.status_code)


def _json(response: httpx2.Response) -> dict[str, Any]:
    _check(response)
    try:
        return cast(dict[str, Any], response.json())
    except json.JSONDecodeError:
        raise Failed("not_json", "a route answered something that isn't JSON") from None
