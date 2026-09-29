"""`atlas tradingview login`: Atlas gets its own OAuth token for TradingView's MCP server.

It follows the MCP authorization specification (2025-06-18), which builds on OAuth 2.1:

1. **Protected resource metadata** (RFC 9728). An unauthenticated `initialize` to the MCP
   server answers 401 with `WWW-Authenticate: Bearer resource_metadata="<url>"`; without
   that parameter, the well-known URIs are tried (`/.well-known/oauth-protected-resource`
   with the MCP path appended, then at the root). The metadata names the authorization
   server(s) and the resource identifier.
2. **Authorization server metadata** (RFC 8414, else OpenID Connect discovery): the
   authorization, token and (optional) registration endpoints. If it lists
   `code_challenge_methods_supported`, `S256` must be among them.
3. **Dynamic client registration** (RFC 7591) when the server offers a registration
   endpoint: a public client (`token_endpoint_auth_method: none`) with the loopback
   redirect URI, for the authorization-code and refresh-token grants. Without one, the
   owner passes `--client-id` (or `ATLAS_TRADINGVIEW_CLIENT_ID`).
4. **Authorization code with PKCE** (S256), a random `state`, and the RFC 8707 `resource`
   parameter (the MCP server's URL). The redirect URI is `http://127.0.0.1:<port>/callback`,
   served by Atlas for the one callback; the owner opens the printed URL in a browser and
   signs in. The callback's `state` must match.
5. **Token request**: the code, the PKCE verifier, the redirect URI and the resource.

The tokens (with the token endpoint and client, so a refresh needs nothing else) are then
written to the token file (mode 0600) or printed for use as secrets. Nothing here logs a
token.
"""

import base64
import hashlib
import re
import secrets
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, cast
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

import httpx2

from atlas import __version__
from atlas.settings import Settings
from atlas.tradingview.mcp import PROTOCOL_VERSION
from atlas.tradingview.tokens import TokenSet, TradingViewAuthError, token_request, token_response

CLIENT_NAME = "Atlas Research"
_RESOURCE_METADATA = re.compile(r'resource_metadata="([^"]+)"')
_SCOPE = re.compile(r'scope="([^"]+)"')


@dataclass(frozen=True)
class AuthorizationServer:
    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    registration_endpoint: str | None
    scopes: list[str] | None  # what to ask for (the resource's advertised scopes), if any


@dataclass
class _Callback:
    params: dict[str, str] | None = None


def discover(client: httpx2.Client, mcp_url: str) -> tuple[str, AuthorizationServer]:
    """The resource identifier and its authorization server, per the MCP authorization spec."""
    challenge = client.post(
        mcp_url,
        json={
            "jsonrpc": "2.0",
            "id": "atlas-login",
            "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "atlas-research", "version": __version__},
            },
        },
        headers={"Accept": "application/json, text/event-stream"},
    )
    header = challenge.headers.get("www-authenticate", "") if challenge.status_code == 401 else ""
    found = _RESOURCE_METADATA.search(header)
    parts = urlsplit(mcp_url)
    origin = f"{parts.scheme}://{parts.netloc}"
    candidates = (
        [found.group(1)]
        if found
        else [
            f"{origin}/.well-known/oauth-protected-resource{parts.path.rstrip('/')}",
            f"{origin}/.well-known/oauth-protected-resource",
        ]
    )
    metadata = _first_json(client, candidates, "protected resource metadata")
    servers = metadata.get("authorization_servers")
    if not isinstance(servers, list) or not servers or not isinstance(servers[0], str):
        raise TradingViewAuthError("the protected resource metadata names no authorization server")
    resource = metadata.get("resource")
    scope = _SCOPE.search(header)
    scopes = (
        scope.group(1).split()
        if scope
        else cast(list[str], metadata.get("scopes_supported"))
        if isinstance(metadata.get("scopes_supported"), list)
        else None
    )
    return (
        resource if isinstance(resource, str) and resource else mcp_url,
        _authorization_server(client, servers[0], scopes),
    )


def _authorization_server(
    client: httpx2.Client, issuer: str, scopes: list[str] | None
) -> AuthorizationServer:
    parts = urlsplit(issuer)
    origin = f"{parts.scheme}://{parts.netloc}"
    path = parts.path.rstrip("/")
    candidates = (
        [
            f"{origin}/.well-known/oauth-authorization-server{path}",
            f"{origin}/.well-known/openid-configuration{path}",
            f"{origin}{path}/.well-known/openid-configuration",
        ]
        if path
        else [
            f"{origin}/.well-known/oauth-authorization-server",
            f"{origin}/.well-known/openid-configuration",
        ]
    )
    metadata = _first_json(client, candidates, "authorization server metadata")
    methods = metadata.get("code_challenge_methods_supported")
    if isinstance(methods, list) and "S256" not in methods:
        raise TradingViewAuthError("the authorization server doesn't support PKCE with S256")
    authorize = metadata.get("authorization_endpoint")
    token = metadata.get("token_endpoint")
    if not isinstance(authorize, str) or not isinstance(token, str):
        raise TradingViewAuthError(
            "the authorization server metadata lacks the authorization or token endpoint"
        )
    registration = metadata.get("registration_endpoint")
    return AuthorizationServer(
        issuer=issuer,
        authorization_endpoint=authorize,
        token_endpoint=token,
        registration_endpoint=registration if isinstance(registration, str) else None,
        scopes=scopes,
    )


def _first_json(client: httpx2.Client, urls: list[str], what: str) -> dict[str, Any]:
    for url in urls:
        try:
            response = client.get(url, headers={"Accept": "application/json"})
        except httpx2.TransportError:
            continue
        if response.is_success:
            try:
                body = response.json()
            except ValueError:
                continue
            if isinstance(body, dict):
                return cast(dict[str, Any], body)
    raise TradingViewAuthError(f"no {what} found (tried {', '.join(urls)})")


def register(
    client: httpx2.Client, server: AuthorizationServer, redirect_uri: str
) -> tuple[str, str | None]:
    """Dynamic client registration: (client_id, client_secret or None)."""
    assert server.registration_endpoint is not None
    response = client.post(
        server.registration_endpoint,
        json={
            "client_name": CLIENT_NAME,
            "redirect_uris": [redirect_uri],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
            **({"scope": " ".join(server.scopes)} if server.scopes else {}),
        },
        headers={"Accept": "application/json"},
    )
    if not response.is_success:
        raise TradingViewAuthError(
            f"client registration failed (HTTP {response.status_code}); pass --client-id instead"
        )
    answer: object = response.json()
    body = cast(dict[str, Any], answer) if isinstance(answer, dict) else {}
    client_id = body.get("client_id")
    if not isinstance(client_id, str) or not client_id:
        raise TradingViewAuthError("client registration answered without a client_id")
    secret = body.get("client_secret")
    return client_id, secret if isinstance(secret, str) and secret else None


def pkce_pair() -> tuple[str, str]:
    """(verifier, S256 challenge), RFC 7636."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return verifier, base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _serve_callback(port: int) -> tuple[HTTPServer, _Callback]:
    received = _Callback()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parts = urlsplit(self.path)
            if parts.path != "/callback":
                self.send_response(404)
                self.end_headers()
                return
            received.params = {k: v[0] for k, v in parse_qs(parts.query).items()}
            body = b"Atlas received the authorization. You can close this tab."
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            pass  # the callback's query holds the authorization code

    return HTTPServer(("127.0.0.1", port), Handler), received


def login(
    settings: Settings,
    *,
    show: Callable[[str], None],
    port: int | None = None,
    client_id: str | None = None,
    timeout: float = 300.0,
    transport: httpx2.BaseTransport | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> TokenSet:
    """Run the authorization flow (see the module); `show` presents the URL to the owner."""
    server, received = _serve_callback(settings.tradingview_login_port if port is None else port)
    redirect_uri = f"http://127.0.0.1:{server.server_address[1]}/callback"
    try:
        with httpx2.Client(
            timeout=settings.tradingview_timeout_seconds,
            transport=transport,
            headers={"User-Agent": settings.exchange_user_agent},
        ) as client:
            resource, authorization = discover(client, settings.tradingview_mcp_url)
            client_id = client_id or settings.tradingview_client_id
            client_secret: str | None = None
            if client_id is None:
                if authorization.registration_endpoint is None:
                    raise TradingViewAuthError(
                        "the authorization server offers no client registration: pass"
                        " --client-id (or set ATLAS_TRADINGVIEW_CLIENT_ID)"
                    )
                client_id, client_secret = register(client, authorization, redirect_uri)
            verifier, challenge = pkce_pair()
            state = secrets.token_urlsafe(32)
            query = {
                "response_type": "code",
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "state": state,
                "resource": resource,
            }
            if authorization.scopes:
                query["scope"] = " ".join(authorization.scopes)
            parts = urlsplit(authorization.authorization_endpoint)
            joined = "&".join(q for q in (parts.query, urlencode(query)) if q)
            show(urlunsplit((parts.scheme, parts.netloc, parts.path, joined, "")))
            params = _wait(server, received, timeout)
            if params.get("state") != state:
                raise TradingViewAuthError("the callback's state doesn't match: sign in again")
            if "error" in params:
                raise TradingViewAuthError(
                    f"the authorization was refused: {params['error'][:200]}"
                )
            code = params.get("code")
            if not code:
                raise TradingViewAuthError("the callback carried no authorization code")
            pending = TokenSet(
                access_token="",  # none yet: the token request answers with it
                token_endpoint=authorization.token_endpoint,
                client_id=client_id,
                client_secret=client_secret,
                resource=resource,
            )
            body = token_request(
                client,
                pending,
                {
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "code_verifier": verifier,
                },
            )
            return token_response(body, pending, clock())
    finally:
        server.server_close()


def _wait(server: HTTPServer, received: _Callback, timeout: float) -> dict[str, str]:
    """Serve requests until the callback arrives or `timeout` seconds pass."""
    done = threading.Event()
    timer = threading.Timer(timeout, done.set)
    timer.start()
    server.timeout = 0.5
    try:
        while received.params is None and not done.is_set():
            server.handle_request()
    finally:
        timer.cancel()
    if received.params is None:
        raise TradingViewAuthError(f"no sign-in within {timeout:g} s: run the login again")
    return received.params
