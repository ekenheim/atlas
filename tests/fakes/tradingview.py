"""A transport-level fake of TradingView's MCP server and its OAuth 2.1 authorization server.

The tool answers are the synthetic fixtures in `tests/fixtures/tradingview/` (see its
manifest; no TradingView content). The protocol follows the MCP specification (2025-06-18):

- `POST /mcp`: JSON-RPC 2.0. `initialize` opens a session (the `Mcp-Session-Id` answer
  header); `notifications/initialized` is answered 202; `tools/call` needs the session ID
  and `MCP-Protocol-Version` headers and answers `{content: [{type: "text", text}]}`, as
  one JSON object or, with `sse=True`, an SSE stream carrying a progress notification
  before the answer. A request without a valid bearer token is answered 401 with
  `WWW-Authenticate: Bearer resource_metadata="..."`; a session in `ended_sessions` 404.
  `DELETE /mcp` ends the session.
- Tools: `mcp-tv-get-documents` (`documents-<company>.json` by symbol), `mcp-tv-get-document-
  view` (`view-<view id>.json`; a view in `unretrievable` answers `isError`),
  `mcp-tv-get-news` (`news-<company>.json`). Any other tool is a JSON-RPC error.
- OAuth: protected resource metadata at `/.well-known/oauth-protected-resource/mcp`
  (authorization server `<origin>/auth`), authorization server metadata at
  `/.well-known/oauth-authorization-server/auth`, dynamic client registration at
  `POST /auth/register`, and `POST /auth/token` for the authorization-code grant (checking
  the PKCE verifier against the challenge `authorize` saw, the redirect URI and the
  resource) and the refresh-token grant (rotating the refresh token). `authorize(url)`
  plays the owner's browser: it reads the authorization URL and returns the loopback
  callback URL with a code and the state.

Every request is kept in `calls` (with the time it arrived, in `times`); tool calls in
`tool_calls`.
"""

import base64
import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx2

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "tradingview"
SYMBOLS = {"NASDAQ:LITE": "lumentum", "HKEX:3308": "innolight"}
ACCESS_TOKEN = "fake-access-token-1"  # a test value, not a TradingView token
REFRESH_TOKEN = "fake-refresh-token-1"
CLIENT_ID = "fake-registered-client"


def fixture_text(name: str) -> str:
    return (FIXTURES / f"{name}.json").read_text(encoding="utf-8")


@dataclass
class FakeTradingView:
    access_tokens: set[str] = field(default_factory=lambda: {ACCESS_TOKEN})
    refresh_tokens: set[str] = field(default_factory=lambda: {REFRESH_TOKEN})
    sse: bool = False
    unretrievable: set[str] = field(default_factory=lambda: {"syn-view-2001-t"})
    ended_sessions: set[str] = field(default_factory=set[str])
    unavailable: bool = False  # answer every MCP request 503
    calls: list[httpx2.Request] = field(default_factory=list[httpx2.Request])
    times: list[float] = field(default_factory=list[float])
    tool_calls: list[tuple[str, dict[str, Any]]] = field(
        default_factory=list[tuple[str, dict[str, Any]]]
    )
    registrations: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    token_requests: list[dict[str, str]] = field(default_factory=list[dict[str, str]])
    sessions: int = 0
    _issued: int = 1
    _codes: dict[str, dict[str, str]] = field(default_factory=dict[str, dict[str, str]])

    @property
    def transport(self) -> httpx2.MockTransport:
        return httpx2.MockTransport(self.handle)

    def mcp_requests(self) -> list[httpx2.Request]:
        return [c for c in self.calls if c.url.path == "/mcp"]

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        self.calls.append(request)
        self.times.append(time.monotonic())
        origin = f"{request.url.scheme}://{request.url.netloc.decode()}"
        path = request.url.path
        if path == "/mcp":
            return self._mcp(request, origin)
        if path == "/.well-known/oauth-protected-resource/mcp":
            return httpx2.Response(
                200,
                json={
                    "resource": f"{origin}/mcp",
                    "authorization_servers": [f"{origin}/auth"],
                    "scopes_supported": ["mcp"],
                },
            )
        if path == "/.well-known/oauth-authorization-server/auth":
            return httpx2.Response(
                200,
                json={
                    "issuer": f"{origin}/auth",
                    "authorization_endpoint": f"{origin}/auth/authorize",
                    "token_endpoint": f"{origin}/auth/token",
                    "registration_endpoint": f"{origin}/auth/register",
                    "code_challenge_methods_supported": ["S256"],
                },
            )
        if path == "/auth/register" and request.method == "POST":
            self.registrations.append(json.loads(request.content))
            return httpx2.Response(201, json={"client_id": CLIENT_ID})
        if path == "/auth/token" and request.method == "POST":
            return self._token(request)
        return httpx2.Response(404)

    # --- the owner's browser ---

    def authorize(self, url: str) -> str:
        """Approve the authorization request at `url`; the callback URL to visit."""
        query = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
        assert query["response_type"] == "code"
        assert query["code_challenge_method"] == "S256"
        code = f"fake-code-{len(self._codes) + 1}"
        self._codes[code] = query
        return f"{query['redirect_uri']}?{urlencode({'code': code, 'state': query['state']})}"

    # --- OAuth token endpoint ---

    def _new_tokens(self) -> dict[str, Any]:
        self._issued += 1
        access, refresh = f"fake-access-token-{self._issued}", f"fake-refresh-token-{self._issued}"
        self.access_tokens.add(access)
        self.refresh_tokens.add(refresh)
        return {
            "access_token": access,
            "refresh_token": refresh,
            "token_type": "Bearer",
            "expires_in": 3600,
        }

    def _token(self, request: httpx2.Request) -> httpx2.Response:
        form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        self.token_requests.append(form)
        if form.get("grant_type") == "authorization_code":
            asked = self._codes.pop(form.get("code", ""), None)
            verifier = form.get("code_verifier", "").encode()
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier).digest()).rstrip(b"=")
            if (
                asked is None
                or challenge.decode() != asked["code_challenge"]
                or form.get("redirect_uri") != asked["redirect_uri"]
                or form.get("client_id") != asked["client_id"]
                or form.get("resource") != asked["resource"]
            ):
                return httpx2.Response(400, json={"error": "invalid_grant"})
            return httpx2.Response(200, json=self._new_tokens())
        if form.get("grant_type") == "refresh_token":
            refresh = form.get("refresh_token", "")
            if refresh not in self.refresh_tokens:
                return httpx2.Response(400, json={"error": "invalid_grant"})
            self.refresh_tokens.discard(refresh)  # rotated
            return httpx2.Response(200, json=self._new_tokens())
        return httpx2.Response(400, json={"error": "unsupported_grant_type"})

    # --- MCP ---

    def _mcp(self, request: httpx2.Request, origin: str) -> httpx2.Response:
        authorization = request.headers.get("authorization", "")
        if authorization.removeprefix("Bearer ") not in self.access_tokens:
            return httpx2.Response(
                401,
                headers={
                    "WWW-Authenticate": 'Bearer resource_metadata="'
                    f'{origin}/.well-known/oauth-protected-resource/mcp"'
                },
            )
        if self.unavailable:
            return httpx2.Response(503, text="unavailable")
        session = request.headers.get("mcp-session-id")
        if request.method == "DELETE":
            return httpx2.Response(200 if session else 400)
        if session in self.ended_sessions:
            return httpx2.Response(404)
        message = json.loads(request.content)
        method = message.get("method")
        if method == "initialize":
            self.sessions += 1
            return httpx2.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": message["id"],
                    "result": {
                        "protocolVersion": message["params"]["protocolVersion"],
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "fake-tradingview", "version": "0"},
                    },
                },
                headers={"Mcp-Session-Id": f"fake-session-{self.sessions}"},
            )
        assert session == f"fake-session-{self.sessions}", "requests carry the session ID"
        if "id" not in message:  # a notification
            return httpx2.Response(202)
        assert request.headers.get("mcp-protocol-version") == "2025-06-18"
        if method != "tools/call":
            return self._answer(message["id"], error={"code": -32601, "message": "not found"})
        name, arguments = message["params"]["name"], message["params"]["arguments"]
        self.tool_calls.append((name, arguments))
        return self._tool(message["id"], name, arguments)

    def _tool(self, request_id: str, name: str, arguments: dict[str, Any]) -> httpx2.Response:
        if name == "mcp-tv-get-documents":
            return self._text(request_id, fixture_text(f"documents-{SYMBOLS[arguments['symbol']]}"))
        if name == "mcp-tv-get-news":
            return self._text(request_id, fixture_text(f"news-{SYMBOLS[arguments['symbol']]}"))
        if name == "mcp-tv-get-document-view":
            view = arguments["view_id"]
            if view in self.unretrievable:
                return self._answer(
                    request_id,
                    result={
                        "content": [{"type": "text", "text": "view not retrievable"}],
                        "isError": True,
                    },
                )
            return self._text(request_id, fixture_text(f"view-{view}"))
        return self._answer(request_id, error={"code": -32602, "message": f"no tool {name}"})

    def _text(self, request_id: str, text: str) -> httpx2.Response:
        return self._answer(request_id, result={"content": [{"type": "text", "text": text}]})

    def _answer(self, request_id: str, *, result: Any = None, error: Any = None) -> httpx2.Response:
        message: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id}
        message.update({"error": error} if error is not None else {"result": result})
        if not self.sse:
            return httpx2.Response(200, json=message)
        progress: dict[str, Any] = {
            "jsonrpc": "2.0",
            "method": "notifications/progress",
            "params": {},
        }
        body = f"event: message\ndata: {json.dumps(progress)}\n\n"
        body += f"id: 1\nevent: message\ndata: {json.dumps(message)}\n\n"
        return httpx2.Response(
            200, content=body.encode(), headers={"Content-Type": "text/event-stream"}
        )
