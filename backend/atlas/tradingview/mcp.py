"""An MCP client over streamable HTTP: TradingView's MCP server, as JSON-RPC 2.0 over POST.

The transport follows the MCP specification (2025-06-18, "Transports: Streamable HTTP"):

- Every JSON-RPC message is one POST to the MCP endpoint, with `Accept: application/json,
  text/event-stream`. A request's answer is either one JSON object (`application/json`) or
  an SSE stream (`text/event-stream`) whose events carry JSON-RPC messages; the one whose
  `id` matches is the answer (other messages on the stream, such as progress notifications,
  are skipped). A notification is answered 202 Accepted, with no body.
- The session starts with `initialize` (the client's protocol version and name), then the
  `notifications/initialized` notification. If the server's answer carries an
  `Mcp-Session-Id` header, every later request sends it back; each also sends
  `MCP-Protocol-Version` with the negotiated version. A 404 to a request carrying the
  session ID means the session has ended: the client starts a new one and retries once.
  Closing sends DELETE with the session ID (a 405 means the server doesn't allow it).
- Authorization (the MCP authorization spec, OAuth 2.1): `Authorization: Bearer <token>` on
  every request; a 401 refreshes the token once (`TokenStore`), then fails clearly.

`tools/call` answers `{content: [{type: "text", text}], isError?}`; TradingView's tools put
their JSON answer in the first text item, which `call_tool` returns both as the exact text
received and parsed.

Every request waits for the rate limiter first (at most one per `1 / rate` seconds). A 429,
a 5xx or an unreachable server raises `TradingViewUnavailable`; any other failure
`McpError`. No token appears in an error.
"""

import json
import logging
import re
import uuid
from dataclasses import dataclass
from typing import Any, Self, cast

import httpx2

from atlas import __version__
from atlas.jobs.pacing import FailedWithArtifacts
from atlas.sources import TokenBucket
from atlas.tradingview.tokens import LOGIN_HINT, TokenStore, TradingViewAuthError

log = logging.getLogger(__name__)

PROTOCOL_VERSION = "2025-06-18"
SESSION_HEADER = "Mcp-Session-Id"
_ERROR_TEXT_LIMIT = 300
_MAX_EVENT_BYTES = 32 * 1024 * 1024  # a long transcript is one event


class McpError(Exception):
    """The MCP server's answer was an error, or not a valid answer."""


class McpToolError(McpError):
    """A tool call the server answered with `isError` (e.g. a view that isn't retrievable)."""


UNPARSED_LIMIT = 4000
CALENDAR_TOOL = "mcp-tv-get-earnings-calendar"

# Consensus is not Atlas's to keep (the owner disallowed it, 2026-10-15), not even in the
# answer a failed job leaves behind. A name that says consensus, an estimate, a forecast, EPS
# (as a word of its own: not `steps`), revenue, a surprise or an actual is taken out.
_CONSENSUS = re.compile(
    r"consensus|estimate|forecast|(?<![a-z])eps(?![a-z])|revenue|surprise|actual|guidance",
    re.IGNORECASE,
)
# The calendar answers consensus EPS and revenue, in values as well as in named keys (a column
# layout holds numbers under a header that names the column), so its answer is kept as a
# skeleton: keys, value types and list lengths, with a value only under a key that names a
# symbol, a date, a period or a status.
_IDENTIFYING_KEY = re.compile(
    r"symbol|ticker|date|time|period|status|fiscal|quarter|year|^id$|_id$"
)
_HEADER_KEY = re.compile(r"field|column|header|schema|names|keys")
_VALUE_LIMIT = 64


def _without_consensus(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _without_consensus(item)
            for key, item in cast(dict[str, Any], value).items()
            if not _CONSENSUS.search(key)
        }
    if isinstance(value, list):
        return [_without_consensus(item) for item in cast(list[Any], value)]
    return value


def _type_name(value: Any) -> str:
    if value is None:
        return "null"
    return type(value).__name__  # str, int, float, bool


def _skeleton(value: Any, key: str = "") -> Any:
    if isinstance(value, dict):
        return {
            name: _skeleton(item, name)
            for name, item in cast(dict[str, Any], value).items()
            if not _CONSENSUS.search(name)
        }
    if isinstance(value, list):
        items = cast(list[Any], value)
        if _HEADER_KEY.search(key.lower()) and all(isinstance(i, str) for i in items):
            # The names of a column layout's columns, so its shape can be fitted.
            return [i[:_VALUE_LIMIT] for i in items if not _CONSENSUS.search(cast(str, i))]
        if not any(isinstance(item, dict | list) for item in items):
            # A column or a row: its length and the type of its values, never the values.
            return f"[{len(items)} x {', '.join(sorted({_type_name(i) for i in items})) or '-'}]"
        return [_skeleton(item, key) for item in items]
    if (
        isinstance(value, str | int | float)
        and not isinstance(value, bool)
        and _IDENTIFYING_KEY.search(key.lower())
        and not (isinstance(value, str) and _CONSENSUS.search(value))
    ):
        return value[:_VALUE_LIMIT] if isinstance(value, str) else value
    return f"<{_type_name(value)}>"


def _without_consensus_lines(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if not _CONSENSUS.search(line))


class UnexpectedAnswer(McpError, FailedWithArtifacts):
    """A tool's answer that isn't in a shape Atlas can use. The job fails at once (trying
    again would get the same answer) and its artifacts keep the first `UNPARSED_LIMIT`
    characters of the answer (`unparsed_answer`, consensus taken out), so the shape can be
    fitted from one live call. The calendar's answer is kept as a skeleton (see above; a
    column layout keeps its column names but not a consensus column's), text that isn't JSON
    without the lines that name consensus; any other tool's JSON loses only the keys that name
    it."""

    def __init__(self, tool: str, detail: str, answer: Any) -> None:
        if tool == CALENDAR_TOOL:
            shown = (
                _without_consensus_lines(answer)
                if isinstance(answer, str)
                else json.dumps(_skeleton(answer))
            )
        elif isinstance(answer, str):
            shown = answer
        else:
            shown = json.dumps(_without_consensus(answer))
        FailedWithArtifacts.__init__(
            self,
            f"{tool}: unexpected answer: {detail}",
            {
                "status": "unexpected_answer",
                "tool": tool,
                "unparsed_answer": shown[:UNPARSED_LIMIT],
            },
        )


class TradingViewUnavailable(McpError):
    """TradingView is throttling (429), failing (5xx) or unreachable; retry later."""


@dataclass(frozen=True)
class ToolResult:
    text: str  # the first text content, exactly as received
    value: Any  # that text parsed as JSON


class McpClient:
    """One MCP session over streamable HTTP (see the module)."""

    def __init__(
        self,
        url: str,
        tokens: TokenStore,
        *,
        limiter: TokenBucket,
        timeout: float,
        user_agent: str,
        transport: httpx2.BaseTransport | None = None,
    ) -> None:
        self._url = url
        self._tokens = tokens
        self._limiter = limiter
        self._client = httpx2.Client(
            timeout=timeout, transport=transport, headers={"User-Agent": user_agent}
        )
        self._session_id: str | None = None
        self._protocol_version: str | None = None
        self._initialized = False

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        try:
            if self._session_id is not None:
                try:
                    self._send("DELETE", None)
                except (McpError, TradingViewAuthError):
                    pass  # the server ends the session itself
        finally:
            self._client.close()

    def call_tool(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        result = self.request("tools/call", {"name": name, "arguments": arguments})
        content = result.get("content")
        texts = [
            item.get("text")
            for item in cast(list[dict[str, Any]], content if isinstance(content, list) else [])
            if isinstance(item, dict) and item.get("type") == "text"  # pyright: ignore[reportUnnecessaryIsInstance]
        ]
        text = next((t for t in texts if isinstance(t, str)), None)
        if result.get("isError"):
            raise McpToolError(f"{name}: {(text or 'error')[:_ERROR_TEXT_LIMIT]}")
        if text is None:
            raise McpError(f"{name}: the answer has no text content")
        try:
            value = json.loads(text)
        except ValueError:
            raise UnexpectedAnswer(name, "the text content isn't JSON", text) from None
        return ToolResult(text=text, value=value)

    def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """Send one JSON-RPC request in the session (starting it first) and return its result."""
        if not self._initialized:
            self._initialize()
        try:
            return self._request(method, params)
        except _SessionEnded:
            log.info("TradingView MCP session ended; starting a new one")
            self._session_id = self._protocol_version = None
            self._initialized = False
            self._initialize()
            return self._request(method, params)

    def _initialize(self) -> None:
        result = self._request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "atlas-research", "version": __version__},
            },
        )
        version = result.get("protocolVersion")
        self._protocol_version = version if isinstance(version, str) else PROTOCOL_VERSION
        self._send("POST", {"jsonrpc": "2.0", "method": "notifications/initialized"})
        self._initialized = True

    def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        request_id = str(uuid.uuid4())
        message = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        answer = self._send("POST", message, request_id=request_id)
        if answer is None:
            raise McpError(f"{method}: no answer")
        error = answer.get("error")
        if error is not None:
            detail = cast(dict[str, Any], error) if isinstance(error, dict) else {}
            raise McpError(
                f"{method}: JSON-RPC error {detail.get('code')}:"
                f" {str(detail.get('message'))[:_ERROR_TEXT_LIMIT]}"
            )
        result = answer.get("result")
        if not isinstance(result, dict):
            raise McpError(f"{method}: the answer has no result object")
        return cast(dict[str, Any], result)

    def _headers(self) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self._tokens.access_token()}",
            "Accept": "application/json, text/event-stream",
        }
        if self._session_id is not None:
            headers[SESSION_HEADER] = self._session_id
        if self._protocol_version is not None:
            headers["MCP-Protocol-Version"] = self._protocol_version
        return headers

    def _send(
        self,
        http_method: str,
        message: dict[str, Any] | None,
        *,
        request_id: str | None = None,
        refreshed: bool = False,
    ) -> dict[str, Any] | None:
        """One HTTP exchange; the JSON-RPC answer to `request_id`, if one was expected."""
        self._limiter.wait()
        try:
            with self._client.stream(
                http_method, self._url, headers=self._headers(), json=message
            ) as response:
                status = response.status_code
                if status == 401:
                    if refreshed or not self._tokens.can_refresh():
                        raise TradingViewAuthError(
                            "TradingView refused the access token (HTTP 401: missing, expired"
                            f" or revoked); {LOGIN_HINT}"
                        )
                    response.close()
                    self._tokens.refresh()
                    return self._send(http_method, message, request_id=request_id, refreshed=True)
                if status == 404 and self._session_id is not None and http_method == "POST":
                    raise _SessionEnded
                if status == 429 or status >= 500:
                    raise TradingViewUnavailable(f"TradingView MCP answered HTTP {status}")
                if not response.is_success:
                    body = response.read().decode("utf-8", "replace")
                    raise McpError(
                        f"TradingView MCP answered HTTP {status}: {body[:_ERROR_TEXT_LIMIT]}"
                    )
                session = response.headers.get(SESSION_HEADER)
                if session:
                    self._session_id = session
                if request_id is None:
                    return None
                return _answer(response, request_id)
        except httpx2.TransportError as error:
            raise TradingViewUnavailable(
                f"TradingView MCP is unreachable: {type(error).__name__}"
            ) from None


class _SessionEnded(Exception):
    """The server no longer knows the session (HTTP 404)."""


def _answer(response: httpx2.Response, request_id: str) -> dict[str, Any]:
    media_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if media_type == "text/event-stream":
        for event in httpx2.EventSource(response, max_event_size=_MAX_EVENT_BYTES):
            if event.event != "message" or not event.data:
                continue
            found = _match(_parse(event.data), request_id)
            if found is not None:
                return found
        raise McpError("the event stream ended without the answer")
    if media_type == "application/json":
        found = _match(_parse(response.read().decode("utf-8")), request_id)
        if found is not None:
            return found
        raise McpError("the JSON answer doesn't answer the request")
    raise McpError(f"unexpected answer type {media_type or 'none'!r}")


def _parse(data: str) -> Any:
    try:
        return json.loads(data)
    except ValueError:
        raise McpError("an answer that isn't JSON") from None


def _match(message: Any, request_id: str) -> dict[str, Any] | None:
    """The JSON-RPC response to `request_id` in `message` (one message or a batch)."""
    candidates = cast(list[object], message) if isinstance(message, list) else [message]
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        candidate = cast(dict[str, Any], candidate)
        if candidate.get("id") == request_id and ("result" in candidate or "error" in candidate):
            return candidate
    return None
