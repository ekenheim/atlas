"""The owner's TradingView OAuth 2.1 tokens: where they live, and refreshing them.

Tokens come from the token file `atlas tradingview login` writes
(`ATLAS_TRADINGVIEW_TOKEN_FILE`, default `.atlas/tradingview-token.json`, mode 0600,
gitignored), else from secrets (`ATLAS_TRADINGVIEW_ACCESS_TOKEN`, optionally
`ATLAS_TRADINGVIEW_REFRESH_TOKEN` with `ATLAS_TRADINGVIEW_TOKEN_URL` and
`ATLAS_TRADINGVIEW_CLIENT_ID`). The file records its own token endpoint and client, so a
refresh needs nothing else.

A refresh (RFC 6749 §6, with the RFC 8707 `resource`, as the MCP authorization spec asks)
happens before a request when the access token has expired (or expires within a minute),
and once after a 401. The new tokens are written back to the token file (a rotated refresh
token included), or kept in memory for tokens from secrets. No token is ever logged, printed
or put in an error message.
"""

import json
import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Self

import httpx2

from atlas.settings import Settings

_EARLY_REFRESH = timedelta(minutes=1)
_ERROR_TEXT_LIMIT = 200
LOGIN_HINT = "run `atlas tradingview login` (docs/runbooks.md, TradingView)"


class TradingViewAuthError(Exception):
    """No usable TradingView token: missing, expired without a refresh, or refused."""


@dataclass(frozen=True)
class TokenSet:
    access_token: str
    refresh_token: str | None = None
    expires_at: datetime | None = None
    token_endpoint: str | None = None
    client_id: str | None = None
    client_secret: str | None = None
    scope: str | None = None
    # RFC 8707: the resource (the MCP server's URL) the tokens were issued for.
    resource: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "token_endpoint": self.token_endpoint,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "scope": self.scope,
            "resource": self.resource,
        }

    @classmethod
    def from_json(cls, value: dict[str, Any]) -> Self:
        access = value.get("access_token")
        if not isinstance(access, str) or not access:
            raise TradingViewAuthError("the TradingView token file has no access_token")
        expires = value.get("expires_at")
        return cls(
            access_token=access,
            refresh_token=value.get("refresh_token") or None,
            expires_at=datetime.fromisoformat(expires) if isinstance(expires, str) else None,
            token_endpoint=value.get("token_endpoint") or None,
            client_id=value.get("client_id") or None,
            client_secret=value.get("client_secret") or None,
            scope=value.get("scope") or None,
            resource=value.get("resource") or None,
        )

    def refreshable(self) -> bool:
        return bool(self.refresh_token and self.token_endpoint and self.client_id)

    def __repr__(self) -> str:  # never show a token
        return f"TokenSet(expires_at={self.expires_at!r}, refreshable={self.refreshable()})"


def write_token_file(path: Path, tokens: TokenSet) -> None:
    """Write `tokens` to `path` atomically, readable by the owner only (mode 0600)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        os.fchmod(handle, 0o600)
        with os.fdopen(handle, "w", encoding="utf-8") as file:
            json.dump(tokens.to_json(), file, indent=2, sort_keys=True)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
    path.chmod(0o600)


def token_response(
    body: dict[str, Any], previous: TokenSet | None, now: datetime, **fields: Any
) -> TokenSet:
    """A token endpoint's successful answer as a TokenSet (keeping the previous refresh token
    when the server didn't rotate it)."""
    access = body.get("access_token")
    if not isinstance(access, str) or not access:
        raise TradingViewAuthError("the token endpoint's answer has no access_token")
    expires_in = body.get("expires_in")
    base = previous or TokenSet(access_token=access)
    return replace(
        base,
        access_token=access,
        refresh_token=body.get("refresh_token") or base.refresh_token,
        expires_at=now + timedelta(seconds=float(expires_in))
        if isinstance(expires_in, int | float)
        else None,
        scope=body.get("scope") or base.scope,
        **fields,
    )


def token_request(client: httpx2.Client, tokens: TokenSet, form: dict[str, str]) -> dict[str, Any]:
    """POST `form` to the token endpoint (a public client sends its client_id; a registered
    secret goes in the body, as `client_secret_post`)."""
    assert tokens.token_endpoint is not None and tokens.client_id is not None
    form = {**form, "client_id": tokens.client_id}
    if tokens.client_secret:
        form["client_secret"] = tokens.client_secret
    if tokens.resource:
        form["resource"] = tokens.resource
    try:
        response = client.post(
            tokens.token_endpoint, data=form, headers={"Accept": "application/json"}
        )
    except httpx2.TransportError as error:
        raise TradingViewAuthError(
            f"the TradingView token endpoint is unreachable: {type(error).__name__}"
        ) from None
    if not response.is_success:
        error_code = ""
        try:
            error_code = str(response.json().get("error", ""))
        except ValueError:
            pass
        raise TradingViewAuthError(
            f"the TradingView token endpoint refused the request (HTTP {response.status_code}"
            + (f", {error_code[:_ERROR_TEXT_LIMIT]}" if error_code else "")
            + f"): {LOGIN_HINT}"
        )
    body = response.json()
    if not isinstance(body, dict):
        raise TradingViewAuthError("the token endpoint's answer isn't a JSON object")
    return body  # pyright: ignore[reportUnknownVariableType]


class TokenStore:
    """The owner's tokens for one process: loaded lazily, refreshed when due."""

    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx2.BaseTransport | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._settings = settings
        self._clock = clock
        self._tokens: TokenSet | None = None
        self._from_file = False
        self._client = httpx2.Client(
            timeout=settings.tradingview_timeout_seconds, transport=transport
        )

    def close(self) -> None:
        self._client.close()

    def _load(self) -> TokenSet:
        if self._tokens is not None:
            return self._tokens
        path = self._settings.tradingview_token_file
        if path.is_file():
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as error:
                raise TradingViewAuthError(
                    f"cannot read the TradingView token file {path}: {type(error).__name__}"
                ) from None
            if not isinstance(value, dict):
                raise TradingViewAuthError(f"the TradingView token file {path} isn't an object")
            self._tokens, self._from_file = TokenSet.from_json(value), True  # pyright: ignore[reportUnknownArgumentType]
            return self._tokens
        settings = self._settings
        if settings.tradingview_access_token is None and settings.tradingview_refresh_token is None:
            raise TradingViewAuthError(
                f"no TradingView token: no token file at {path} and no"
                f" ATLAS_TRADINGVIEW_ACCESS_TOKEN; {LOGIN_HINT}"
            )
        refresh = settings.tradingview_refresh_token
        self._tokens = TokenSet(
            access_token=settings.tradingview_access_token.get_secret_value()
            if settings.tradingview_access_token
            else "",
            refresh_token=refresh.get_secret_value() if refresh else None,
            # Unknown expiry: a missing access token is refreshed at once.
            expires_at=None
            if settings.tradingview_access_token
            else datetime.min.replace(tzinfo=UTC),
            token_endpoint=settings.tradingview_token_url,
            client_id=settings.tradingview_client_id,
            resource=settings.tradingview_mcp_url,
        )
        return self._tokens

    def can_refresh(self) -> bool:
        return self._load().refreshable()

    def access_token(self) -> str:
        """A current access token, refreshed first if it has expired."""
        tokens = self._load()
        if tokens.expires_at is not None and tokens.expires_at - _EARLY_REFRESH <= self._clock():
            if not tokens.refreshable():
                raise TradingViewAuthError(
                    f"the TradingView access token expired at {tokens.expires_at.isoformat()}"
                    f" and there is no refresh token; {LOGIN_HINT}"
                )
            tokens = self.refresh()
        return tokens.access_token

    def refresh(self) -> TokenSet:
        """Exchange the refresh token for new tokens, and keep them (the file too)."""
        tokens = self._load()
        if not tokens.refreshable():
            raise TradingViewAuthError(
                f"TradingView refused the access token and it can't be refreshed; {LOGIN_HINT}"
            )
        assert tokens.refresh_token is not None
        body = token_request(
            self._client,
            tokens,
            {"grant_type": "refresh_token", "refresh_token": tokens.refresh_token},
        )
        self._tokens = token_response(body, tokens, self._clock())
        if self._from_file:
            write_token_file(self._settings.tradingview_token_file, self._tokens)
        return self._tokens
